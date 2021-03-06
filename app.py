#!/usr/bin/env python2

import os
import re
import time
import shlex
from bottle import route, template, request, static_file, redirect, response, default_app, hook
import config
import preferences
import structured_metrics
from graphs import Graphs
from backend import Backend, get_action_on_rules_match
import logging


# contains all errors as key:(title,msg) items.
# will be used throughout the runtime to track all encountered errors
errors = {}

# will contain the latest data
last_update = None

logger = logging.getLogger('app')
logger.setLevel(logging.DEBUG)
chandler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
chandler.setFormatter(formatter)
logger.addHandler(chandler)
if config.log_file:
    fhandler = logging.FileHandler(config.log_file)
    fhandler.setFormatter(formatter)
    logger.addHandler(fhandler)

logger.debug('app starting')
backend = Backend(config)
s_metrics = structured_metrics.StructuredMetrics(config)
graphs = Graphs()
graphs.load_plugins()
graphs_all = graphs.list_graphs()


def parse_query(query_str):
    query = {
        'patterns': [],
        'group_by': ['target_type=', 'what=', 'server'],
        'sum_by': [],
        'avg_by': [],
    }
    # for a call like ('foo bar baz quux', 'bar ', 'baz', 'def')
    # returns ('foo quux', 'baz') or the original query and the default val if no match

    def parse_out_value(query_str, predicate_match, value_match, value_default):
        match = re.search('(%s%s)' % (predicate_match, value_match), query_str)
        value = value_default
        if match and match.groups() > 0:
            value = match.groups(1)[0].replace(predicate_match, '')
            query_str = query_str[:match.start(1)] + query_str[match.end(1):]
        return (query_str, value)

    (query_str, query['statement']) = parse_out_value(query_str, '^', '(graph|list) ', 'graph')
    query['statement'] = query['statement'].rstrip()

    (query_str, query['to']) = parse_out_value(query_str, 'to ', '[^ ]+', 'now')
    (query_str, query['from']) = parse_out_value(query_str, 'from ', '[^ ]+', '-24hours')

    (query_str, group_by_str) = parse_out_value(query_str, 'GROUP BY ', '[^ ]+', None)
    (query_str, extra_group_by_str) = parse_out_value(query_str, 'group by ', '[^ ]+', None)
    (query_str, sum_by_str) = parse_out_value(query_str, 'sum by ', '[^ ]+', None)
    (query_str, avg_by_str) = parse_out_value(query_str, 'avg by ', '[^ ]+', None)
    if group_by_str is not None:
        query['group_by'] = group_by_str.split(',')
    elif extra_group_by_str is not None:
        query['group_by'] = [tag for tag in query['group_by'] if tag.endswith('=')]
        query['group_by'].extend(extra_group_by_str.split(','))
    if sum_by_str is not None:
        query['sum_by'] = sum_by_str.split(',')
        # We must remove tag from the groupby if used as an aggregate.
        for tag in query['sum_by']:
            if tag in query['group_by']:
                query['group_by'].remove(tag)
    if avg_by_str is not None:
        query['avg_by'] = avg_by_str.split(',')
        # We must remove tag from the groupby if used as an aggregate.
        for tag in query['avg_by']:
            if tag in query['group_by']:
                query['group_by'].remove(tag)
    for tag in query['group_by']:
        if tag.endswith('='):
            query['patterns'].append(tag)

    (query_str, query['limit_targets']) = parse_out_value(query_str, 'limit ', '[^ ]+', 500)

    # split query_str into multiple patterns which are all matched independently
    # this allows you write patterns in any order, and also makes it easy to use negations
    query['patterns'] += shlex.split(query_str, comments=True)
    return query


# id, data -> an key:object from the dict of objects
# pattern: a pattern structure from match()
def match_pattern(id, data, pattern):
    if 'match_tag_equality' in pattern:
        t_key = pattern['match_tag_equality'][0]
        t_val = pattern['match_tag_equality'][1]
        if len(t_key) is 0 and len(t_val) is 0:
            # this pattern is pointless.
            match_pattern = True
        if len(t_key) > 0 and len(t_val) is 0:
            match_pattern = (t_key in data['tags'])
        if len(t_key) is 0 and len(t_val) > 0:
            match_pattern = False
            for v in data['tags'].values():
                if t_val is v:
                    match_pattern = True
                    break
        if len(t_key) > 0 and len(t_val) > 0:
            match_pattern = (t_key in data['tags'] and data['tags'][t_key] == t_val)
    elif 'match_tag_regex' in pattern:
        t_key = pattern['match_tag_regex'][0]
        t_val = pattern['match_tag_regex'][1]
        if len(t_key) is 0 and len(t_val) is 0:
            # this pattern is pointless.
            match_pattern = True
        if len(t_key) > 0 and len(t_val) is 0:
            match_pattern = False
            for k in data['tags'].iterkeys():
                if re.search(t_key, k) is not None:
                    match_pattern = True
                    break
        if len(t_key) is 0 and len(t_val) > 0:
            match_pattern = False
            for v in data['tags'].values():
                if re.search(t_val, v) is not None:
                    match_pattern = True
                    break
        if len(t_key) > 0 and len(t_val) > 0:
            match_pattern = (t_key in data['tags'] and re.search(t_val, data['tags'][t_key]) is not None)
    else:
        match_pattern = (pattern['match_id_regex'].search(id) is not None)
    return match_pattern


# objects is expected to be a dict with elements like id: data
# id's are matched, and the return value is a dict in the same format
# if you use tags, make sure data['tags'] is a dict of tags or this'll blow up
# if graph, ignores patterns that only apply for targets (tag matching on target_type, what)
def match(objects, query, graph=False):
    patterns = structured_metrics.parse_patterns(query)
    objects_matching = {}
    for (id, data) in objects.items():
        match_o = True
        for pattern in patterns.values():
            match_p = match_pattern(id, data, pattern)
            if match_p and pattern['negate']:
                match_o = False
            elif not match_p and not pattern['negate']:
                match_o = False
        if match_o:
            objects_matching[id] = data
    return objects_matching


@route('<path:re:/assets/.*>')
@route('<path:re:/timeserieswidget/.*js>')
@route('<path:re:/timeserieswidget/.*css>')
@route('<path:re:/timeserieswidget/timezone-js/src/.*js>')
@route('<path:re:/timeserieswidget/tz/.*>')
@route('<path:re:/DataTables/media/js/.*js>')
@route('<path:re:/DataTablesPlugins/integration/bootstrap/.*js>')
@route('<path:re:/DataTablesPlugins/integration/bootstrap/.*css>')
def static(path):
    return static_file(path, root='.')


@route('/', method='GET')
@route('/index', method='GET')
@route('/index/', method='GET')
@route('/index/<query>', method='GET')
def index(query=''):
    from suggested_queries import suggested_queries
    body = template('templates/body.index', errors=errors, query=query, suggested_queries=suggested_queries)
    return render_page(body)


@route('/dashboards')
@route('/dashboards/<dashboard_name>')
def slash_dashboards(dashboard_name=None):
    if dashboard_name:
        try:
            d = __import__('dashboards.%s' % dashboard_name, globals(), locals(), ['queries'])
        except Exception, e:
            errors['dashboard_%s' % dashboard_name] = ("Failed to load dashboard '%s'" % dashboard_name, e)
            body = template('templates/body.dashboards', errors=errors)
            return render_page(body, 'dashboards')
        dashboard = template('templates/body.dashboard', errors=errors, dashboard=dashboard_name, queries=d.queries)
        return render_page(dashboard)
    else:
        dashboard = template('templates/body.dashboards', errors=errors)
        return render_page(dashboard)


def render_page(body, page='index'):
    return unicode(template('templates/page', body=body, page=page, last_update=last_update))


@route('/index', method='POST')
def index_post():
    redirect('/index/%s' % request.forms.query)


@route('/meta')
def meta():
    body = template('templates/body.meta', todo=template('templates/' + 'todo'.upper()))
    return render_page(body, 'meta')


# accepts comma separated list of metric_id's
@route('/inspect/<metrics>')
def inspect_metric(metrics=''):
    metrics = map(s_metrics.load_metric, metrics.split(','))
    args = {'errors': errors,
            'metrics': metrics,
            }
    body = template('templates/body.inspect', args)
    return render_page(body, 'inspect')


@route('/debug')
@route('/debug/<query>')
def view_debug(query=''):
    if 'metrics_file' in errors:
        body = template('templates/snippet.errors', errors=errors)
        return render_page(body, 'debug')
    if query:
        query = parse_query(query)
        targets_matching = s_metrics.matching(query)
        graphs_matching = match(graphs_all, query, True)
        graphs_targets, graphs_targets_options = build_graphs_from_targets(targets_matching, query)
        targets = targets_matching
        graphs = graphs_matching
    else:
        return "Not implemented. TODO time to deprecate this?"

    args = {'errors': errors,
            'targets': targets,
            'graphs': graphs,
            'graphs_targets': graphs_targets,
            'graphs_targets_options': graphs_targets_options
            }
    body = template('templates/body.debug', args)
    return render_page(body, 'debug')


@route('/debug/metrics')
def debug_metrics():
    response.content_type = 'text/plain'
    if 'metrics_file' in errors:
        response.status = 500
        return errors
    return "\n".join(sorted(s_metrics.list_metric_ids()))


def build_graphs(graphs, query={}):
    defaults = {
        'from': '-24hours',
        'to': 'now'
    }
    query = dict(defaults.items() + query.items())
    query['until'] = query['to']
    del query['to']
    for (k, v) in graphs.items():
        v.update(query)
    return graphs


def graphs_limit_targets(graphs, limit):
    targets_used = 0
    unlimited_graphs = graphs
    graphs = {}
    limited_reached = False
    for (graph_key, graph_config) in unlimited_graphs.items():
        if limited_reached:
            break
        graphs[graph_key] = graph_config
        unlimited_targets = graph_config['targets']
        graphs[graph_key]['targets'] = []
        for target in unlimited_targets:
            targets_used += 1
            graphs[graph_key]['targets'].append(target)
            if targets_used == limit:
                limited_reached = True
                break
    return graphs


def graphite_func_aggregate(targets, query, aggfunc):
    t = {
        'target': '%s(%s)' % (aggfunc, ','.join([t['target'] for t in targets])),
        'graphite_metric': [t['graphite_metric'] for t in targets],
        'variables': targets[0]['variables']
    }
    for s_b in query:
        t['variables'][s_b] = '%s (%s values)' % (aggfunc, len(targets))
    return t


def build_graphs_from_targets(targets, query={}):
    # merge default options..
    defaults = {
        'group_by': [],
        'sum_by': [],
        'avg_by': [],
        'from': '-24hours',
        'to': 'now',
        'statement': 'graph',
        'limit_targets': 500
    }
    query = dict(defaults.items() + query.items())
    graphs = {}
    if not targets:
        return (graphs, query)
    group_by = query['group_by']
    sum_by = query['sum_by']
    avg_by = query['avg_by']
    # for each combination of values of tags from group_by, make 1 graph with
    # all targets that have these values. so for each graph, we have:
    # the "constants": tags in the group_by
    # the "variables": tags not in the group_by, which can have arbitrary values
    # go through all targets and group them into graphs:
    for (i, target_id) in enumerate(sorted(targets.iterkeys())):
        constants = {}
        variables = {}
        target_data = targets[target_id]
        for (tag_name, tag_value) in target_data['tags'].items():
            if tag_name in group_by or '%s=' % tag_name in group_by:
                constants[tag_name] = tag_value
            else:
                variables[tag_name] = tag_value
        graph_key = '__'.join([target_data['tags'][tag_name] for tag_name in constants])
        if graph_key not in graphs:
            graph = {'from': query['from'], 'until': query['to']}
            graph.update({'constants': constants, 'targets': []})
            graphs[graph_key] = graph
        # set all options needed for timeserieswidget/flot:
        t = {
            'variables': variables,
            'graphite_metric': target_data['id'],
            'target': target_data['id']
        }
        if 'color' in target_data:
            t['color'] = target_data['color']
        graphs[graph_key]['targets'].append(t)

    # sum targets together if appropriate
    if (sum_by or avg_by):
        for (graph_key, graph_config) in graphs.items():
            graph_config['targets_sum_candidates'] = {}
            graph_config['targets_avg_candidates'] = {}
            graph_config['normal_targets'] = []
            all_targets = graph_config['targets'][:]  # Get a copy

            for target in all_targets:
                # targets that can get summed together with other tags, must
                # have at least 1 'sum_by' tags in the variables list.
                # targets that can get summed together must have:
                # * the same 'sum_by' tags
                # * the same variables (key and val), except those vals that
                # are being summed by.
                # so for every group of sum_by tags and variables we build a
                # list of targets that can be summed together
                variables = target['variables'].keys()
                sum_constants = set(sum_by).intersection(set(variables))
                if sum_constants:
                    sum_constants_str = '_'.join(sorted(sum_constants))
                    variables_str = '_'.join(
                        ['%s_%s' % (k, target['variables'][k]) \
                            for k in sorted(variables) \
                            if k not in sum_constants])
                    sum_id = '%s__%s' % (sum_constants_str, variables_str)
                    if sum_id not in graph_config['targets_sum_candidates']:
                        graphs[graph_key]['targets_sum_candidates'][sum_id] = []
                    graph_config['targets_sum_candidates'][sum_id].append(target)

            for (sum_id, targets) in graph_config['targets_sum_candidates'].items():
                if len(targets) > 1:
                    for t in targets:
                        all_targets.remove(t)
                    all_targets.append(
                        graphite_func_aggregate(targets, sum_by, "sumSeries"))

            for target in all_targets:
                # Now, if we combine average and sum, we must process average
                # based on sum targets.
                # If we don't find any avg target match, just add plain sum targets.
                variables = target['variables'].keys()
                avg_constants = set(avg_by).intersection(set(variables))
                if avg_constants:
                    avg_constants_str = '_'.join(sorted(avg_constants))
                    variables_str = '_'.join(
                        ['%s_%s' % (k, target['variables'][k]) \
                            for k in sorted(variables) \
                            if k not in avg_constants])
                    avg_id = '%s__%s' % (avg_constants_str, variables_str)
                    if avg_id not in graph_config['targets_avg_candidates']:
                        graph_config['targets_avg_candidates'][avg_id] = []
                    graph_config['targets_avg_candidates'][avg_id].append(target)

            for (avg_id, targets) in graph_config['targets_avg_candidates'].items():
                if len(targets) > 1:
                    for t in targets:
                        all_targets.remove(t)
                    all_targets.append(
                        graphite_func_aggregate(targets, avg_by, "averageSeries"))

            graph_config["targets"] = all_targets

    # remove targets/graphs over the limit
    graphs = graphs_limit_targets(graphs, query['limit_targets'])

    # if in a graph all targets have a tag with the same value, they are
    # effectively constants, so promote them.  this makes the display of the
    # graphs less rendundant and paves the path
    # for later configuration on a per-graph basis.
    for (graph_key, graph_config) in graphs.items():
        # get all variable tags throughout all targets in this graph
        tags_seen = set()
        for target in graph_config['targets']:
            for tag_name in target['variables'].keys():
                tags_seen.add(tag_name)

        # find effective constants from those variables,
        # and effective variables. (unset tag is a value too)
        first_values_seen = {}
        effective_variables = set()  # tags for which we've seen >1 values
        for target in graph_config['targets']:
            for tag_name in tags_seen:
                # already known that we can't promote, continue
                if tag_name in effective_variables:
                    continue
                tag_value = target['variables'].get(tag_name, None)
                if tag_name not in first_values_seen:
                    first_values_seen[tag_name] = tag_value
                elif tag_value != first_values_seen[tag_name]:
                    effective_variables.add(tag_name)
        effective_constants = tags_seen - effective_variables

        # promote the effective_constants by adjusting graph and targets:
        graphs[graph_key]['promoted_constants'] = {}
        for tag_name in effective_constants:
            graphs[graph_key]['promoted_constants'][tag_name] = first_values_seen[tag_name]
            for (i, target) in enumerate(graph_config['targets']):
                if tag_name in graphs[graph_key]['targets'][i]['variables']:
                    del graphs[graph_key]['targets'][i]['variables'][tag_name]

        # now that graph config is "rich", merge in settings from preferences
        constants = dict(graphs[graph_key]['constants'].items() + graphs[graph_key]['promoted_constants'].items())
        for graph_option in get_action_on_rules_match(preferences.graph_options, constants):
            if isinstance(graph_option, dict):
                graphs[graph_key].update(graph_option)
            else:
                graphs[graph_key] = graph_option(graphs[graph_key])
    return (graphs, query)


@route('/graphs/', method='POST')
@route('/graphs/<query>', method='GET')  # used for manually testing
def graphs(query=''):
    '''
    get all relevant graphs matching query,
    graphs from structured_metrics targets, as well as graphs
    defined in structured_metrics plugins
    '''
    if 'metrics_file' in errors:
        return template('templates/graphs', errors=errors)
    if not query:
        query = request.forms.get('query')
    if not query:
        return template('templates/graphs', query=query, errors=errors)
    query = parse_query(query)
    tags = set()
    targets_matching = s_metrics.matching(query)
    for target in targets_matching.values():
        for tag_name in target['tags'].keys():
            tags.add(tag_name)
    graphs_matching = match(graphs_all, query, True)
    graphs_matching = build_graphs(graphs_matching, query)
    stats = {'len_targets_all': s_metrics.count_metrics(),
             'len_graphs_all': len(graphs_all),
             'len_targets_matching': len(targets_matching),
             'len_graphs_matching': len(graphs_matching),
             }
    out = ''
    graphs = []
    targets_list = {}
    # the code to handle different statements, and the view
    # templates could be a bit prettier, but for now it'll do.
    if query['statement'] == 'graph':
        graphs_targets_matching = build_graphs_from_targets(targets_matching, query)[0]
        stats['len_graphs_targets_matching'] = len(graphs_targets_matching)
        graphs_matching.update(graphs_targets_matching)
        stats['len_graphs_matching_all'] = len(graphs_matching)
        if len(graphs_matching) > 0 and request.headers.get('X-Requested-With') != 'XMLHttpRequest':
            out += template('templates/snippet.graph-deps')
        for key in sorted(graphs_matching.iterkeys()):
            graphs.append((key, graphs_matching[key]))
    elif query['statement'] == 'list':
        # for now, only supports targets, not graphs
        targets_list = targets_matching
        stats['len_graphs_targets_matching'] = 0
        stats['len_graphs_matching_all'] = 0

    args = {'errors': errors,
            'query': query,
            'config': config,
            'graphs': graphs,
            'targets_list': targets_list,
            'tags': tags,
            'preferences': preferences
            }
    args.update(stats)
    out += template('templates/graphs', args)
    return out


# vim: ts=4 et sw=4:
