%graph_id = graph_key.replace('.','').replace('-','_').replace(' ','_') # disallowed in var names
<h2 id="h2_{{graph_id}}"></h2>
%try: import json
%except ImportError: import simplejson as json
        <div class="chart_container flot" id="chart_container_flot_{{graph_id}}">
            <div class="chart" id="chart_flot_{{graph_id}}" height="300px" width="700px"></div>
            <div class="legend" id="legend_flot_{{graph_id}}"></div>
            <form class="toggler" id="line_stack_form_flot_{{graph_id}}"></form>
        </div>
        <script language="javascript">
	    $(document).ready(function () {
		var graph_data = {{!json.dumps(graph_data)}};
        graph_data['constants_all'] = jQuery.extend({}, graph_data['constants'], graph_data['promoted_constants']);

        $("#h2_{{graph_id}}").html(get_graph_name("{{graph_key}}", graph_data));
        vtitle = get_vtitle(graph_data);
        if (vtitle != "") {
            graph_data["vtitle"] = vtitle;
        }

        // interactive legend elements -> use labelFormatter (specifying name: '<a href..>foo</a>' doesn't work)
        // but this function only sees the label and series, so any extra data must be encoded in the label
        labelFormatter = function(label, series) {
            var data = JSON.parse(label);
            if(data.name) {
                // name attribute is already set. this is probably a predefined graph, not generated from targets
                return data.name;
            }
            name = "";
            // at some point, we'll probably want to order the variables; just like how we compose graph titles.
            $.map(data["variables"], function (v,k) { name += " " + display_tag(k, v);});
            // there's nothing about this target that's not already in the graph title
            if (name == "") {
                name = "empty";
            }
            return get_inspect_url(data, name);
        }
        $.map(graph_data['targets'], function (v,k) {
            v["name"] = JSON.stringify(v, null, 2);
        });
		var defaults = {
		    graphite_url: "{{config.graphite_url}}/render/",
            % if config.anthracite_url is not None:
		    anthracite_url: "{{config.anthracite_url}}",
            % end
		    from: "-24hours",
		    until: "now",
		    height: "300",
		    width: "740",
		    line_stack_toggle: 'line_stack_form_flot_{{graph_id}}',
		    series: {stack: true, lines: { show: true, lineWidth: 0, fill: true }},
		    legend: {container: '#legend_flot_{{graph_id}}', noColumns: 1, labelFormatter: labelFormatter },
            hover_details: true,
            zoneFileBasePath: '../timeserieswidget/tz',
            tz: "{{preferences.timezone}}",
		};
		var graph_flot_{{graph_id}} = $.extend({}, defaults, graph_data);
		$("#chart_flot_{{graph_id}}").graphiteFlot(graph_flot_{{graph_id}}, function(err) { console.log(err); });
		//$("#chart_flot_{{graph_id}}").graphiteHighcharts(graph_flot_{{graph_id}}, function(err) { console.log(err); });
        // TODO: error callback should actually show the errors in the html, something like:
        // function(err) { $("#chart_flot_{{graph_id}}").append('<span class="label label-important">' + err + '</span>'); }
	});
        </script>
