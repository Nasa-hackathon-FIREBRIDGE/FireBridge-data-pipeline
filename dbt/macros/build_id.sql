{% macro build_id() %}
  '{{ var("build_id") }}'::uuid
{% endmacro %}
