import json
import os
import re
from pathlib import Path
from collections import defaultdict
from .config import CLAUDE_DIR

def parse_yaml_frontmatter(content: str) -> dict:
    """Extracts yaml frontmatter from markdown files."""
    match = re.search(r'^---\n(.*?)\n---', content, re.DOTALL)
    if not match:
        return {}
    yaml_text = match.group(1)
    
    data = {}
    for line in yaml_text.split('\n'):
        if ':' in line:
            parts = line.split(':', 1)
            key = parts[0].strip()
            # Basic quoted string unescaping
            val = parts[1].strip()
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            elif val.startswith("'") and val.endswith("'"):
                val = val[1:-1]
            data[key] = val
    return data

def get_mcps() -> list[dict]:
    claude_json_path = Path.home() / ".claude.json"
    if not claude_json_path.exists():
        return []
    
    try:
        data = json.loads(claude_json_path.read_text())
        mcp_servers = data.get("mcpServers", {})
        
        results = []
        for name, config in mcp_servers.items():
            command = config.get("command", "")
            args = " ".join(config.get("args", []))
            full_command = f"{command} {args}".strip()
            
            results.append({
                "id": name,
                "name": name,
                "description": full_command if full_command else "No description available",
                "type": "mcp"
            })
        return results
    except Exception as e:
        print(f"Error parsing MCP config: {e}")
        return []

def get_agents() -> list[dict]:
    agents_dir = CLAUDE_DIR / "agents"
    if not agents_dir.exists():
        return []
    
    results = []
    for md_file in agents_dir.glob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
            frontmatter = parse_yaml_frontmatter(content)
            
            name = frontmatter.get("name", md_file.stem)
            desc = frontmatter.get("description", "No description provided.")
            
            results.append({
                "id": md_file.stem,
                "name": name,
                "description": desc,
                "type": "agent"
            })
        except Exception:
            pass
            
    # Sort agents alphabetically
    results.sort(key=lambda x: x["name"].lower())
    return results

def get_skills() -> list[dict]:
    results = []
    seen = set()
    
    # 1. User Skills (~/.claude/skills/*/)
    skills_dir = CLAUDE_DIR / "skills"
    if skills_dir.exists():
        for skill_folder in skills_dir.iterdir():
            if not skill_folder.is_dir():
                continue
            skill_md = skill_folder / "SKILL.md"
            if skill_md.exists():
                try:
                    content = skill_md.read_text(encoding="utf-8")
                    frontmatter = parse_yaml_frontmatter(content)
                    skill_id = skill_folder.name
                    if skill_id not in seen:
                        seen.add(skill_id)
                        results.append({
                            "id": skill_id,
                            "name": frontmatter.get("name", skill_id),
                            "description": frontmatter.get("description", "No description provided."),
                            "type": "skill"
                        })
                except Exception:
                    pass

    # 2. User Commands (~/.claude/commands/**/*.md)
    commands_dir = CLAUDE_DIR / "commands"
    if commands_dir.exists():
        for md_file in commands_dir.rglob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")
                frontmatter = parse_yaml_frontmatter(content)
                name = frontmatter.get("name", md_file.stem)
                if md_file.parent != commands_dir:
                    prefix = md_file.parent.name
                    if not name.startswith(prefix + ":"):
                        name = f"{prefix}:{name}"
                
                skill_id = name
                if skill_id not in seen:
                    seen.add(skill_id)
                    results.append({
                        "id": md_file.stem,
                        "name": name,
                        "description": frontmatter.get("description", "No description provided."),
                        "type": "skill"
                    })
            except Exception:
                pass

    # 3. Plugin Skills (~/.claude/plugins/installed_plugins.json)
    plugins_json = CLAUDE_DIR / "plugins" / "installed_plugins.json"
    if plugins_json.exists():
        try:
            data = json.loads(plugins_json.read_text(encoding="utf-8"))
            plugins = data.get("plugins", {})
            for plugin_versions in plugins.values():
                for version in plugin_versions:
                    install_path = version.get("installPath")
                    if install_path:
                        install_dir = Path(install_path)
                        if install_dir.exists():
                            for md_file in install_dir.rglob("SKILL.md"):
                                try:
                                    content = md_file.read_text(encoding="utf-8")
                                    frontmatter = parse_yaml_frontmatter(content)
                                    name = frontmatter.get("name", md_file.parent.name)
                                    
                                    skill_id = name
                                    if skill_id not in seen:
                                        seen.add(skill_id)
                                        results.append({
                                            "id": md_file.parent.name,
                                            "name": name,
                                            "description": frontmatter.get("description", "No description provided."),
                                            "type": "skill"
                                        })
                                except Exception:
                                    pass
        except Exception as e:
            print(f"Error parsing installed_plugins.json: {e}")
            
    # Sort alphabetically
    results.sort(key=lambda x: x["name"].lower())
    return results

def get_all_resources() -> dict:
    return {
        "mcps": get_mcps(),
        "agents": get_agents(),
        "skills": get_skills()
    }
