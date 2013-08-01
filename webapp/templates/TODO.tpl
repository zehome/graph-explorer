<ul>
    <li>show all contributing targets in aggregated targets</li>
    <li>consider: on gh-page top: say why you'd want to use it over stock dashboard. move targets between graphs</li>
    <li>some kind of UI feature that suggests tags keys/vals, to make it easier for newbies</li>
    <li>remove statically configured "suggested queries" (or make it an optional module). instead, track last_use and times_used of each query (after ordering), and show popular queries based on frecency. and/or allow saving queries with manual notes</li>
    <li>define how to generate (multiple) targets for any metric (to render as a count, a rate, etc)</li>
    <li>display tags properly (colored labels) on other pages like debug, inspect</li>
    <li>allow "or" style matches across groups of patterns,like so: cpu iowait dfs || plugin=udp dfs1. maybe this can be integrated with the above</li>
    <li>i.e. timeouts, disconnects are 'whats' for which it can make sense to graph them together. maybe as 'events'? but how to define this configuration? (see swift_proxy_server)
    -> postprocess with rules to add more tags?</li>
    <li>"global" rules -> everything with server:df.* -> tag env=prod-df</li>
    <li>fix what/type/target_type for timers in all plugins (already done in catchall_statsd)</li>
    <li>'consolidate by <timespan interval>' phrase, or just interactive slider.</li>
    <li>number of put/delete requests arriving on swift proxy</li>
    <li>group by scale automatically: if things differ by orders of magnitude, put them on different graphs</li>
    <li>if graphite can't handle the syntax and the graphite http request errors out, show nice error boxes</li>
    <li>counters of number of objects, objects added/deleted per second (needs plugin for monitoring agent)</li>
    <li>order by graph_name DESC etc</li>
    <li>simplify tags semantics: only have tags when they matched something. then we can probably remove some stuff from the language syntax.
we can achieve this with post-processing tag metadata, or even better: avoid empty tags in the first place (which can be done by using a list of regexes where named groups must be non-empty,
but enforcing that might be a bit too much (and cause us to write to many similar regexes.. either i think checks for 'tag key exists' are useless
because they only depend on how the regex was defined, if user wants to match on tag, key must obviously always exist.)</li>
    <li>histograms will be better (see http://localhost:8080/index/bin_%20group%20by%20type) after: 1) don't display empty tags in title 2) fix target colors</li>
    <li>filestat: display percentage as assigned/max ? same idea for disk used and others. maybe a new generic target type thing</li>
    <li>auto adjust height of graphs based on #targets. with many targets, the legends start to overlap</li>
    <li>a way to distribute this including deps directly for easy and reliable install</li>
    <li>filter by expression (graphite function(s) or simplified). example: "where movingAverage(10h) &gt; 100" </li>
    <li>allow updating metrics.json file from a dropdown menu when you hoover over 'last metrucs update'</li>
    <li>ajax refresh for 'last metrics update'</li>
    <li>plugin for http://obfuscurity.com/2012/06/Watching-the-Carbon-Feed</li>
    <li>maybe... under query, suggest tags, and even patterns (by going over metrics, stripping out all tags and listing what remains, uniqued)</li>
</ul>
Ponderings:
<ul>
<li>
note: graphiteStats.last_exception can be rendered as "unix timestamp in seconds" and "age in seconds"
what: "last_exception age" ? no cause it should be on the same graph as last_flush age (same "what") so maybe what is "age in seconds" en what_extra last_expcetion?
so what is not necessarily the intrinsic thing we're monitoring, but what we're displaying on the graph
</li>
<li>automatic different extra rendering modes or "angles" (i.e. default is count or something, rate (default implementation is just `derivative()`), if a rate is stored,
integral to get running total, multiple movingAverages, ...)
but make them all overridable. (e.g. load plugin can use the stored 5/15m averages because those targets are just available)
</li>
</ul>
