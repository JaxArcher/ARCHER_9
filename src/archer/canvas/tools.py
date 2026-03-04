"""
Canvas rendering tools for ARCHER agents.

Allows agents to create visual artifacts (charts, tables, diagrams)
when appropriate.
"""

CANVAS_TOOLS = [
    {
        'name': 'create_chart',
        'description': 'Create an interactive chart to visualize data. Use when data would be clearer as a chart than as text. Supports pie, bar, line, and doughnut charts.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'chart_type': {
                    'type': 'string',
                    'enum': ['pie', 'bar', 'line', 'doughnut'],
                    'description': 'Type of chart to create'
                },
                'title': {
                    'type': 'string',
                    'description': 'Chart title'
                },
                'data': {
                    'type': 'object',
                    'description': 'Chart data as key-value pairs. Keys are labels, values are numbers.',
                    'additionalProperties': {'type': 'number'}
                }
            },
            'required': ['chart_type', 'title', 'data']
        }
    },
    {
        'name': 'create_table',
        'description': 'Create a formatted table to display structured data. Use when data has multiple columns/rows.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'title': {
                    'type': 'string',
                    'description': 'Table title'
                },
                'headers': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'description': 'Column headers'
                },
                'rows': {
                    'type': 'array',
                    'items': {
                        'type': 'array',
                        'items': {'type': 'string'}
                    },
                    'description': 'Table rows'
                }
            },
            'required': ['title', 'headers', 'rows']
        }
    }
]
