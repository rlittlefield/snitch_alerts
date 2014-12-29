$(function() {
    $("#three").hide();
    $.ajax({
        'url': 'app/config',
        'method': 'get',
        'success': function(data) {
            for (key in data) {
                var value = data[key];
                $("#"+key).val(value);
            }
            $("#three").show();
        }
    });
});