#!/usr/bin/env python2

import preferences
import structured_metrics
import config
from core.graphs import Graphs
from core.query import parse_query, normalize_query, parse_patterns
from core.simple_match import match
from core.backend import get_action_on_rules_match
import logging


# contains all errors as key:(title,msg) items.
# will be used throughout the runtime to track all encountered errors
errors = {}

# will contain the latest data
last_update = None
logger = logging.getLogger('app')


class GraphExplorer(object):
    def __init__(self):
        self.s_metrics = structured_metrics.StructuredMetrics(config)
        self.graphs_all = []
        logger.debug('app starting')
        self.load()

    def load(self):
        graphs = Graphs()
        graphs.load_plugins()
        self.graphs_all = graphs.list_graphs()

    def render_graphs(self, query):
        query = parse_query(query)
        (query, target_modifiers) = normalize_query(query)
        patterns = parse_patterns(query)
        # tags listing
        tags = set()
        targets_matching = self.s_metrics.matching(patterns)
        for target in targets_matching.values():
            for tag_name in target['tags'].keys():
                tags.add(tag_name)
        graphs_matching = match(self.graphs_all, patterns, True)
        graphs_matching = build_graphs(graphs_matching, query)
        stats = {'len_targets_all': self.s_metrics.count_metrics(),
                 'len_graphs_all': len(self.graphs_all),
                 'len_targets_matching': len(targets_matching),
                 'len_graphs_matching': len(graphs_matching),
                 }
        graphs = []
        targets_list = {}
        # the code to handle different statements, and the view
        # templates could be a bit prettier, but for now it'll do.
        if query['statement'] == 'graph':
            graphs_targets_matching = build_graphs_from_targets(
                 targets_matching, query, target_modifiers)[0]
            stats['len_graphs_targets_matching'] = len(graphs_targets_matching)
            graphs_matching.update(graphs_targets_matching)
            stats['len_graphs_matching_all'] = len(graphs_matching)
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
                'graphs_matching': graphs_matching,
                'targets_list': targets_list,
                'tags': tags,
                'preferences': preferences
                }
        args.update(stats)
        return args


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


def build_graphs_from_targets(targets, query={}, target_modifiers=[]):
    # merge default options..
    defaults = {
        'group_by': [],
        'sum_by': [],
        'avg_over': None,
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
    avg_over = query['avg_over']
    # i'm gonna assume you never use second and your datapoints are stored with
    # minutely resolution. later on we can use config options for this (or
    # better: somehow query graphite about it)
    # note, the day/week/month numbers are not technically accurate, but
    # since we're doing movingAvg that's ok
    averaging = {
        'M': 1,
        'h': 60,
        'd': 60 * 24,
        'w': 60 * 24 * 7,
        'mo': 60 * 24 * 30
    }
    if avg_over is not None:
        avg_over_amount = avg_over[0]
        avg_over_unit = avg_over[1]
        if avg_over_unit in averaging.keys():
            multiplier = averaging[avg_over_unit]
            target_modifier = ['movingAverage', str(avg_over_amount * multiplier)]
            target_modifiers.append(target_modifier)

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
        target = target_data['id']
        # set all options needed for timeserieswidget/flot:
        t = {
            'variables': variables,
            'id': target_data['id'],  # timeserieswidget doesn't care about this
            'target': target
        }
        if 'color' in target_data:
            t['color'] = target_data['color']
        graphs[graph_key]['targets'].append(t)

    # sum targets together if appropriate
    if len(sum_by):
        for (graph_key, graph_config) in graphs.items():
            graph_config['targets_sum_candidates'] = {}
            graph_config['normal_targets'] = []
            for target in graph_config['targets']:
                # targets that can get summed together with other tags, must
                # have at least 1 'sum_by' tags in the variables list.
                # targets that can get summed together must have:
                # * the same 'sum_by' tags
                # * the same variables (key and val), except those vals that
                # are being summed by.
                # so for every group of sum_by tags and variables we build a
                # list of targets that can be summed together
                sum_constants = set(sum_by).intersection(set(target['variables'].keys()))
                if(sum_constants):
                    sum_constants_str = '_'.join(sorted(sum_constants))
                    variables_str = '_'.join(['%s_%s' % (k, target['variables'][k]) for k in sorted(target['variables'].keys()) if k not in sum_constants])
                    sum_id = '%s__%s' % (sum_constants_str, variables_str)
                    if sum_id not in graphs[graph_key]['targets_sum_candidates']:
                        graphs[graph_key]['targets_sum_candidates'][sum_id] = []
                    graphs[graph_key]['targets_sum_candidates'][sum_id].append(target)
                else:
                    graph_config['normal_targets'].append(target)
            graph_config['targets'] = graph_config['normal_targets']
            for (sum_id, targets) in graphs[graph_key]['targets_sum_candidates'].items():
                if (len(targets) == 1):
                    graph_config['targets'].append(targets[0])
                else:
                    t = {
                        'target': 'sumSeries(%s)' % (','.join([t['target'] for t in targets])),
                        'id': [t['id'] for t in targets],
                        'variables': targets[0]['variables']
                    }
                    for s_b in sum_by:
                        t['variables'][s_b] = 'multi (%s values)' % len(targets)

                    graph_config['targets'].append(t)

    # remove targets/graphs over the limit
    graphs = graphs_limit_targets(graphs, query['limit_targets'])

    # Apply target modifiers (like movingAverage, summarize, ...)
    for (graph_key, graph_config) in graphs.items():
        for target in graph_config['targets']:
            for target_modifier in target_modifiers:
                target['target'] = "%s(%s,%s)" % (target_modifier[0],
                                                  target['target'],
                                                  ','.join(target_modifier[1:]))
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

# vim: ts=4 et sw=4:
