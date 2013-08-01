# -*- coding: utf-8 -*-

from bottle import route, template, request, static_file, redirect, response, default_app
from app import *

# contains all errors as key:(title,msg) items.
# will be used throughout the runtime to track all encountered errors
errors = {}

logger.setLevel(logging.DEBUG)
chandler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
chandler.setFormatter(formatter)
logger.addHandler(chandler)
if config.log_file:
    fhandler = logging.FileHandler(config.log_file)
    fhandler.setFormatter(formatter)
    logger.addHandler(fhandler)
logger = logging.getLogger('webapp')


@route('<path:re:/assets/.*>')
@route('<path:re:/timeserieswidget/.*js>')
@route('<path:re:/timeserieswidget/.*css>')
@route('<path:re:/timeserieswidget/timezone-js/src/.*js>')
@route('<path:re:/timeserieswidget/tz/.*>')
@route('<path:re:/DataTables/media/js/.*js>')
@route('<path:re:/DataTablesPlugins/integration/bootstrap/.*js>')
@route('<path:re:/DataTablesPlugins/integration/bootstrap/.*css>')
def static(path):
    return static_file(path, root='webapp')

@route('/', method='GET')
@route('/index', method='GET')
@route('/index/', method='GET')
@route('/index/<query:path>', method='GET')
def index(query=''):
    from suggested_queries import suggested_queries
    body = template('webapp/templates/body.index', errors=errors, query=query, suggested_queries=suggested_queries)
    return render_page(body)


@route('/dashboard/<dashboard_name>')
def slash_dashboard(dashboard_name=None):
    dashboard = template('webapp/templates/dashboards/%s' % dashboard_name, errors=errors)
    return render_page(dashboard)


def render_page(body, page='index'):
    return unicode(template('webapp/templates/page', body=body, page=page, last_update=last_update))


@route('/meta')
def meta():
    body = template('webapp/templates/body.meta', todo=template('webapp/templates/' + 'todo'.upper()))
    return render_page(body, 'meta')


# accepts comma separated list of metric_id's
@route('/inspect/<metrics>')
def inspect_metric(metrics=''):
    metrics = map(s_metrics.load_metric, metrics.split(','))
    args = {'errors': errors,
            'metrics': metrics,
            }
    body = template('webapp/templates/body.inspect', args)
    return render_page(body, 'inspect')

@route('/graphs/', method='POST')
@route('/graphs/<query>', method='GET')  # used for manually testing
def graphs(query=''):
    '''
    get all relevant graphs matching query,
    graphs from structured_metrics targets, as well as graphs
    defined in structured_metrics plugins
    '''
    if 'metrics_file' in errors:
        return template('webapp/templates/graphs', errors=errors)
    if not query:
        query = request.forms.get('query')
    if not query:
        return template('webapp/templates/graphs', query=query, errors=errors)

    return render_graphs(query)


@route('/graphs_minimal/<query>', method='GET')
def graphs_minimal(query=''):
    '''
    like graphs(), but without extra decoration, so can be used on dashboards
    TODO dashboard should show any errors
    '''
    if not query:
        return template('webapp/templates/graphs', query=query, errors=errors)
    return render_graphs(query, minimal=True)


def render_graphs(query, minimal=False):
    ge = GraphExplorer()
    data = ge.render_graphs(query)
    out = ''

    if data['query']['statement'] == 'graph':
        if (data['graphs_matching'] and 
            request.headers.get('X-Requested-With') != 'XMLHttpRequest'):
            out += template('webapp/templates/snippet.graph-deps')
    if minimal:
        out += template('webapp/templates/graphs_minimal', data)
    else:
        out += template('webapp/templates/graphs', data)
    return out

# vim: ts=4 et sw=4:
