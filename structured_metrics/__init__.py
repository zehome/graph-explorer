import os
import re
import sys
from inspect import isclass
import sre_constants
try:
    import json
except ImportError:
    try:
        import simplejson as json
    except ImportError:
        raise ImportError("GE requires python2, 2.6 or higher, or 2.5 with simplejson.")
sys.path.append("%s/structured_metrics/%s" % (os.getcwd(), 'requests'))
sys.path.append("%s/structured_metrics/%s" % (os.getcwd(), 'rawes'))

import rawes
import requests


query_all = {
    "query_string": {
        "query": "*"
    }
}
def es_query(query, k, v):
    return {
        'query' : {
            query: {
                k: v
            }
        }
    }
def es_regexp(k, v):
    return {
        'regexp': {
            k: v
        }
    }
def hit_to_metric(hit):
    tags = {}
    for tag in hit['_source']['tags']:
        (k, v) = tag.split('=')
        tags[str(k)] = str(v)
    return {
        'id': hit['_id'],
        'tags': tags
    }


class PluginError(Exception):

    def __init__(self, plugin, msg, underlying_error):
        self.plugin = plugin
        self.msg = msg
        self.underlying_error = underlying_error

    def __str__(self):
        return "%s -> %s (%s)" % (self.plugin, self.msg, self.underlying_error)


class StructuredMetrics(object):

    def __init__(self, config):
        self.plugins = []
        self.es = rawes.Elastic("%s:%s" % (config.es_host, config.es_port))

    def load_plugins(self):
        '''
        loads all the plugins sub-modules
        returns encountered errors, doesn't raise them because
        whoever calls this function defines how any errors are
        handled. meanwhile, loading must continue
        '''
        from plugins import Plugin
        import plugins
        errors = []
        plugins_dir = os.path.dirname(plugins.__file__)
        wd = os.getcwd()
        os.chdir(plugins_dir)
        for f in os.listdir("."):
            if f == '__init__.py' or not f.endswith(".py"):
                continue
            module = f[:-3]
            try:
                imp = __import__('plugins.' + module, globals(), locals(), ['*'])
            except Exception, e:
                errors.append(PluginError(module, "Failed to add plugin '%s'" % module, e))
                continue

            for itemname in dir(imp):
                item = getattr(imp, itemname)
                if isclass(item) and item != Plugin and issubclass(item, Plugin):
                    try:
                        self.plugins.append((module, item()))
                    # regex error is too vague to stand on its own
                    except sre_constants.error, e:
                        e = "error problem parsing matching regex: %s" % e
                        errors.append(PluginError(module, "Failed to add plugin '%s'" % module, e))
                    except Exception, e:
                        errors.append(PluginError(module, "Failed to add plugin '%s'" % module, e))
        os.chdir(wd)
        # sort plugins by their matching priority
        self.plugins = sorted(self.plugins, key=lambda t: t[1].priority, reverse=True)
        return errors

    def list_targets(self, metrics):
        for plugin in self.plugins:
            (plugin_name, plugin_object) = plugin
            plugin_object.reset_target_yield_counters()
        targets = {}
        for metric in metrics:
            metric_matched = False
            for (i, plugin) in enumerate(self.plugins):
                (plugin_name, plugin_object) = plugin
                for (k, v) in plugin_object.find_targets(metric):
                    metric_matched = True
                    tags = v['tags']
                    if ('what' not in tags or 'target_type' not in tags) and 'unit' not in tags:
                        print "WARNING: metric", v, "doesn't have the mandatory tags. ignoring it..."
                    if v['graphite_metric'] != v['target']:
                        print "WARNING: deprecated: plugin %s yielded metric with different target then graphite metric for %s" % (plugin_name, v['graphite_metric'])
                        # TODO if we don't yield here, probably the catchall
                        # plugin will just yield it in an inferior way.
                    else:
                        # old style: what and target_type tags, new style: unit tag
                        # automatically add new style for all old style metrics
                        if 'unit' not in tags and 'what' in tags and 'target_type' in tags:
                            convert = {
                                'bytes': 'B',
                                'bits': 'b'
                            }
                            unit = convert.get(tags['what'], tags['what'])
                            if tags['target_type'] is 'rate':
                                v['tags']['unit'] = '%s/s' % unit
                            else:
                                v['tags']['unit'] = unit
                        targets[k] = v
                    if metric_matched:
                        break
        return targets


    def update_targets(self, metrics):
        # using >1 threads/workers/connections would make this faster

        bulk_size = 1000
        bulk_list = []
        targets = self.list_targets(metrics)

        # too slow:
        #for target in targets.values():
        #    self.es.put('graphite_metrics/metric/%s' % target['graphite_metric'], data={
        #        'tags': ['%s=%s' % tuple(tag) for tag in target['tags'].items()]
        #    })

        def flush(bulk_list):
            print 'flushing..'
            if not len(bulk_list):
                return
            body = '\n'.join(map(json.dumps, bulk_list))+'\n'
            self.es.post('graphite_metrics/metric/_bulk', data=body)

        for target in targets.values():
            bulk_list.append({'index': {'_id': target['graphite_metric']}})
            bulk_list.append({'tags': ['%s=%s' % tuple(tag) for tag in target['tags'].items()]})
            if len(bulk_list) >= bulk_size:
                flush(bulk_list)
                bulk_list = []
        flush(bulk_list)

    def load_metric(self, metric_id):
        hit = self.get(metric_id)
        return hit_to_metric(hit)


    def count_metrics(self):
        # TODO
        return 0

    def build_es_query(self, query):
        conditions = []
        for (k, data) in query.items():
            negate = data['negate']
            print k, data
            if 'match_tag_equality' in data:
                data = data['match_tag_equality']
                if data[0] and data[1]:
                    condition = es_query('match', 'tags', "%s=%s" % tuple(data))
                elif data[0]:
                    condition = es_regexp('tags', "%s=.*" % data[0]) # i think a '^' prefix is implied here
                elif data[1]:
                    condition = es_regexp('tags', ".*=%s$" % data[0])
            elif 'match_tag_regex' in data:
                data = data['match_tag_regex']
                if data[0] and data[1]:
                    condition = es_regexp('tags', '%s=.*%s.*' % tuple(data)) # i think a '^' prefix is implied here
                elif data[0]:
                    condition = es_regexp('tags', '.*%s.*=.*' % data[0])
                elif data[1]:
                    condition = es_regexp('tags', '.*=.*%s.*' % data[1])
            elif 'match_id_regex' in data:
                # here 'id' is to be interpreted loosely, as in the old
                # (python-native datastructures) approach where we used
                # Plugin.get_target_id to have an id that contains the graphite
                # metric, but also the tags etc. so if the user types just a
                # word, we want the metrics to be returned where the id or tags
                # are matched
                condition = {
                    "or": [
                        es_regexp('_id', '.*%s.*' % k),
                        es_regexp('tags', '.*%s.*' % k)
                    ]
                }
            if negate:
                condition = { "not": condition }
            conditions.append(condition)
        es_query = {
            "filtered": {
                "query": { "match_all" : { }},
                "filter": {
                    "and": conditions
                }
            }
        }
        return es_query

    def get_metrics(self, query=None):
        try:
            if query is None:
                query = query_all
            return self.es.get('graphite_metrics/metric/_search?size=1000', data={
                "query": query,
            })
        except requests.exceptions.ConnectionError as e:
            sys.stderr.write("Could not connect to ElasticSearch: %s" % e)

    def get(self, metric_id):
        return self.es.get('graphite_metrics/metric/%s' % metric_id)


    def matching(self, query):
        # this is very inefficient :(
        # future optimisation: query['limit_targets'] can be applied if no
        # sum_by or kind of later aggregation
        """
        query looks like so:
        {'patterns': ['target_type=', 'what=', '!tag_k=not_equals_thistag_v', 'tag_k:match_this_val', 'arbitrary', 'words']
        }
        after parsing:
        {
        'tag_k=not_equals_thistag_v': {'negate': True, 'match_tag_equality': ['tag_k', 'not_equals_thistag_v']},
        'target_type=':               {'negate': False, 'match_tag_equality': ['target_type', '']},
        'what=':                      {'negate': False, 'match_tag_equality': ['what', '']},
        'tag_k:match_this_val':       {'negate': False, 'match_tag_regex': ['tag_k', 'match_this_val']},
        'words':                      {'negate': False, 'match_id_regex': <_sre.SRE_Pattern object at 0x2612cb0>},
        'arbitrary':                  {'negate': False, 'match_id_regex': <_sre.SRE_Pattern object at 0x7f6cc000bd90>}
        }
        """
        query = parse_patterns(query)
        es_query = self.build_es_query(query)
        metrics = self.get_metrics(es_query)
        results = {}
        for hit in metrics['hits']['hits']:
            metric = hit_to_metric(hit)
            results[metric['id']] = metric
        return results

    def build_metrics(self, rows):
        results = {}
        for (metric_id, tag_key, tag_val) in rows:
            try:
                results[metric_id]['tags'][tag_key] = tag_val
            except KeyError:
                results[metric_id] = {
                    'graphite_metric': metric_id,
                    'tags': {
                        tag_key: tag_val
                    }
                }
        return results


def parse_patterns(query, graph=False):
    # prepare higher performing query structure
    # note that if you have twice the exact same "word" (ignoring leading '!'), the last one wins
    patterns = {}
    for pattern in query['patterns']:
        negate = False
        if pattern.startswith('!'):
            negate = True
            pattern = pattern[1:]
        patterns[pattern] = {'negate': negate}
        if '=' in pattern:
            if not graph or pattern not in ('target_type=', 'what='):
                patterns[pattern]['match_tag_equality'] = pattern.split('=')
            else:
                del patterns[pattern]
        elif ':' in pattern:
            if not graph or pattern not in ('target_type:', 'what:'):
                patterns[pattern]['match_tag_regex'] = pattern.split(':')
            else:
                del patterns[pattern]
        else:
            patterns[pattern]['match_id_regex'] = re.compile(pattern)
    return patterns
