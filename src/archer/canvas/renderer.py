import json
import time
from pathlib import Path
from typing import Dict, Any, List
'''
Canvas artifact rendering for ARCHER agents.

Converts agent responses into visual artifacts.
'''
import json
import os
from pathlib import Path
from typing import Dict, Any


def render_portfolio_chart(data: Dict[str, Any]) -> str:
    '''Render portfolio data as interactive chart.'''
    template_path = Path(__file__).parent / 'templates' / 'chart.html'
    output_path = Path('data') / 'artifacts' / 'portfolio_latest.html'
    output_path.parent.mkdir(exist_ok=True)
    
    # Read template
    template = template_path.read_text()
    
    # Prepare chart data
    chart_data = {
        'labels': list(data.keys()),
        'datasets': [{
            'label': 'Portfolio Allocation',
            'data': list(data.values()),
            'backgroundColor': [
                'rgba(255, 99, 132, 0.8)',
                'rgba(54, 162, 235, 0.8)',
                'rgba(255, 206, 86, 0.8)',
                'rgba(75, 192, 192, 0.8)',
                'rgba(153, 102, 255, 0.8)',
            ]
        }]
    }
    
    # Inject data into template
    html = template.replace('{{DATA}}', json.dumps(chart_data))
    html = html.replace('{{CHART_TYPE}}', 'pie')
    html = html.replace('{{TITLE}}', 'Portfolio Breakdown')
    
    # Write output
    output_path.write_text(html)
    
    return str(output_path.absolute())


def execute_canvas_tool(tool_name: str, tool_input: Dict[str, Any]) -> Dict[str, Any]:
    '''Execute a canvas tool and return the artifact path.'''
    
    if tool_name == 'create_chart':
        html_path = render_chart(
            chart_type=tool_input['chart_type'],
            title=tool_input['title'],
            data=tool_input['data']
        )
        return {
            'success': True,
            'artifact_path': html_path,
            'message': f"Chart created: {tool_input['title']}"
        }
    
    elif tool_name == 'create_table':
        html_path = render_table(
            title=tool_input['title'],
            headers=tool_input['headers'],
            rows=tool_input['rows']
        )
        return {
            'success': True,
            'artifact_path': html_path,
            'message': f"Table created: {tool_input['title']}"
        }
    
    return {'success': False, 'error': 'Unknown canvas tool'}


def render_chart(chart_type: str, title: str, data: Dict[str, float]) -> str:
    '''Render a chart using the template.'''
    template_path = Path(__file__).parent / 'templates' / 'chart.html'
    output_path = Path('data') / 'artifacts' / f'chart_{int(time.time())}.html'
    output_path.parent.mkdir(exist_ok=True, parents=True)
    
    template = template_path.read_text()
    
    # Prepare Chart.js data
    chart_data = {
        'labels': list(data.keys()),
        'datasets': [{
            'label': title,
            'data': list(data.values()),
            'backgroundColor': [
                'rgba(255, 99, 132, 0.8)',
                'rgba(54, 162, 235, 0.8)',
                'rgba(255, 206, 86, 0.8)',
                'rgba(75, 192, 192, 0.8)',
                'rgba(153, 102, 255, 0.8)',
                'rgba(255, 159, 64, 0.8)',
            ]
        }]
    }
    
    html = template.replace('{{DATA}}', json.dumps(chart_data))
    html = html.replace('{{CHART_TYPE}}', chart_type)
    html = html.replace('{{TITLE}}', title)
    
    output_path.write_text(html)
    return str(output_path.absolute())


def render_table(title: str, headers: List[str], rows: List[List[str]]) -> str:
    '''Render a table as HTML.'''
    output_path = Path('data') / 'artifacts' / f'table_{int(time.time())}.html'
    output_path.parent.mkdir(exist_ok=True, parents=True)
    
    html = f'''<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ background: #1e1e1e; color: #fff; font-family: system-ui; padding: 20px; }}
        h2 {{ color: #4a9eff; text-align: center; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        th {{ background: #2a2a2a; padding: 12px; text-align: left; border: 1px solid #444; }}
        td {{ padding: 10px; border: 1px solid #333; }}
        tr:nth-child(even) {{ background: #252525; }}
    </style>
</head>
<body>
    <h2>{title}</h2>
    <table>
        <thead>
            <tr>{''.join(f'<th>{h}</th>' for h in headers)}</tr>
        </thead>
        <tbody>
            {''.join('<tr>' + ''.join(f'<td>{cell}</td>' for cell in row) + '</tr>' for row in rows)}
        </tbody>
    </table>
</body>
</html>'''
    
    output_path.write_text(html)
    return str(output_path.absolute())
