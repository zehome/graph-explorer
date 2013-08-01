%for (title, msg) in errors.values():
    <div class="row">
     %include webapp/templates/snippet.error title=title, msg=msg
    </div>
