"""
ARCHER Skills Registry.

Dynamically discovers and loads tool definitions from *_SKILL.md files.
"""

import re
from pathlib import Path
from typing import List, Dict, Any


def load_all_skills() -> Dict[str, Any]:
    """Load all skills from *_SKILL.md files."""
    skills_dir = Path(__file__).parent
    skill_files = list(skills_dir.glob('*_SKILL.md'))
    
    all_tools = []
    tool_categories = {}
    
    for skill_file in skill_files:
        skill_data = parse_skill_file(skill_file)
        category = skill_data['category']
        
        for tool in skill_data['tools']:
            all_tools.append(tool)
            tool_categories[tool['name']] = category
    
    return {
        'tools': all_tools,
        'categories': tool_categories
    }


def parse_skill_file(filepath: Path) -> Dict[str, Any]:
    """Parse a SKILL.md file and extract tool definitions."""
    content = filepath.read_text(encoding='utf-8')
    
    # Extract frontmatter
    pattern = r'^---\s*\n(.*?)\n---'
    frontmatter_match = re.search(pattern, content, re.DOTALL | re.MULTILINE)
    
    if not frontmatter_match:
        raise ValueError(f'No frontmatter in {filepath}')
    
    frontmatter = frontmatter_match.group(1)
    metadata = {}
    
    for line in frontmatter.split('\n'):
        if ':' in line:
            key, value = line.split(':', 1)
            metadata[key.strip()] = value.strip()
    
    # Extract tool sections
    tools = []
    tool_sections = re.split(r'\n###? ', content)
    
    for section in tool_sections[1:]:
        tool = parse_tool_section(section, metadata.get('category', 'general'))
        if tool:
            tools.append(tool)
    
    return {
        'name': metadata.get('name', ''),
        'description': metadata.get('description', ''),
        'category': metadata.get('category', 'general'),
        'tools': tools
    }


def parse_tool_section(section: str, category: str) -> Dict[str, Any]:
    """Parse a single tool section from SKILL.md."""
    lines = section.split('\n')
    tool_name = lines[0].strip()

    # Skip section headers (contain parentheses or 'Tools')
    if '(' in tool_name or ')' in tool_name or 'Tools' in tool_name:
        return None
    
    description_lines = []
    parameters = {}
    in_description = False
    
    for line in lines[1:]:
        line = line.strip()
        
        if line.startswith('**Parameters:**'):
            in_description = False
            continue
        
        if line.startswith('**') or line.startswith('###'):
            in_description = False
            continue
        
        if line and not line.startswith('-') and not in_description:
            in_description = True
        
        if in_description and line:
            description_lines.append(line)
        
        # Parse parameters
        if line.startswith('- '):
            match = re.match(r'- (\w+):\s*(.+)', line)
            if match:
                param_name = match.group(1)
                param_desc = match.group(2)
                
                # Determine type
                param_type = 'string'
                if 'integer' in param_desc.lower():
                    param_type = 'integer'
                elif 'array' in param_desc.lower():
                    param_type = 'array'
                elif 'object' in param_desc.lower():
                    param_type = 'object'
                
                required = '(optional)' not in param_desc.lower()
                
                parameters[param_name] = {
                    'type': param_type,
                    'description': param_desc.replace('(optional)', '').strip(),
                    'required': required
                }
    
    description = ' '.join(description_lines)
    required_params = [k for k, v in parameters.items() if v.get('required', True)]
    
    properties = {
        k: {'type': v['type'], 'description': v['description']}
        for k, v in parameters.items()
    }
    
    return {
        'name': tool_name,
        'description': description,
        'input_schema': {
            'type': 'object',
            'properties': properties,
            'required': required_params
        }
    }


_SKILLS_CACHE = None


def get_all_tools() -> List[Dict[str, Any]]:
    """Get all tool schemas from all skills."""
    global _SKILLS_CACHE
    if _SKILLS_CACHE is None:
        _SKILLS_CACHE = load_all_skills()
    return _SKILLS_CACHE['tools']


def get_tool_category(tool_name: str) -> str:
    """Get the category for a specific tool."""
    global _SKILLS_CACHE
    if _SKILLS_CACHE is None:
        _SKILLS_CACHE = load_all_skills()
    return _SKILLS_CACHE['categories'].get(tool_name, 'general')
