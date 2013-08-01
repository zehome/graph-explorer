%include webapp/templates/snippet.errors errors=errors
% if query and not errors:
    <script language="javascript">
    tags = {{!list(tags)}};
    colormap = create_colormap(tags);
    </script>
    % for (k,v) in graphs:
        % include webapp/templates/snippet.graph config=config, graph_key=k, graph_data=v, preferences=preferences
    % end
    <!-- approximation of get_inspect_url(data, name) that works as long as list mode doesn't support sum by (or other kind of N metrics in 1 target) -->
    % for target_id in targets_list.iterkeys():
        <a href="/inspect/{{targets_list[target_id]['id']}}">{{target_id}}</a></br>
    % end
% end
