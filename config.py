graphite_url = 'http://graphitemachine'
anthracite_url = None
listen_host = '0.0.0.0'  # defaults to "all interfaces"
listen_port = 8080
filename_metrics = 'metrics.json'
log_file = 'graph-explorer.log'
es_host = "es_host"
es_port = 9200

# Don't edit after this line
import urlparse
graphite_url_render = urlparse.urljoin(graphite_url, "render/")
graphite_url_metrics = urlparse.urljoin(graphite_url, "metrics", "index.json")
