from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class RegistryError(ValueError):
    """Raised when registry content is invalid or cannot be resolved safely."""


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    path: Path


class Registry:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.manifest_path = self.root / "manifest.yaml"

    def _safe_path(self, relative_path: str) -> Path:
        candidate = (self.root / relative_path).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise RegistryError(f"Path escapes registry root: {relative_path}")
        return candidate

    def manifest(self) -> dict[str, Any]:
        if not self.manifest_path.is_file():
            raise RegistryError(f"Missing manifest: {self.manifest_path}")
        parsed = yaml.safe_load(self.manifest_path.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            raise RegistryError("Registry manifest must be a mapping")
        if parsed.get("schemaVersion") != 1:
            raise RegistryError("Unsupported or missing schemaVersion; expected 1")
        return parsed

    def profile(self, name: str = "default") -> dict[str, Any]:
        profiles = self.manifest().get("profiles")
        if not isinstance(profiles, dict) or name not in profiles:
            raise RegistryError(f"Unknown profile: {name}")
        profile = profiles[name]
        if not isinstance(profile, dict):
            raise RegistryError(f"Profile must be a mapping: {name}")
        return profile

    def instructions(self, profile: str = "default") -> str:
        paths = self.profile(profile).get("instructions", [])
        if not isinstance(paths, list) or not all(isinstance(item, str) for item in paths):
            raise RegistryError(f"Profile instructions must be a list of paths: {profile}")
        documents: list[str] = []
        for relative_path in paths:
            path = self._safe_path(relative_path)
            if not path.is_file():
                raise RegistryError(f"Missing instruction file: {relative_path}")
            documents.append(path.read_text(encoding="utf-8").strip())
        return "\n\n---\n\n".join(documents)

    def skills(self) -> list[Skill]:
        skills_root = self._safe_path("skills")
        if not skills_root.exists():
            return []
        skills: list[Skill] = []
        for path in sorted(skills_root.glob("*/SKILL.md")):
            text = path.read_text(encoding="utf-8")
            metadata = self._frontmatter(text, path)
            name = metadata.get("name")
            description = metadata.get("description")
            if not isinstance(name, str) or name != path.parent.name:
                raise RegistryError(f"Skill name must match its directory: {path}")
            if not isinstance(description, str) or not description.strip():
                raise RegistryError(f"Skill description is required: {path}")
            skills.append(Skill(name=name, description=description, path=path))
        return skills

    def skill_document(self, name: str) -> str:
        if "/" in name or "\\" in name or name in {"", ".", ".."}:
            raise RegistryError(f"Invalid skill name: {name}")
        path = self._safe_path(f"skills/{name}/SKILL.md")
        if not path.is_file():
            raise RegistryError(f"Unknown skill: {name}")
        return path.read_text(encoding="utf-8")

    def prompt_template(self, name: str) -> str:
        if "/" in name or "\\" in name or name in {"", ".", ".."}:
            raise RegistryError(f"Invalid prompt name: {name}")
        path = self._safe_path(f"prompts/{name}.md")
        if not path.is_file():
            raise RegistryError(f"Unknown prompt: {name}")
        return path.read_text(encoding="utf-8")

    def runner_for(self, skill_name: str) -> str:
        runners = self.manifest().get("runners", {})
        if not isinstance(runners, dict):
            raise RegistryError("Manifest runners must be a mapping")
        runner = runners.get(skill_name)
        if not isinstance(runner, str):
            raise RegistryError(f"Skill has no allow-listed runner: {skill_name}")
        return runner

    def search(self, query: str) -> list[dict[str, str]]:
        normalized = query.strip().casefold()
        if not normalized:
            raise RegistryError("Search query cannot be empty")
        results: list[dict[str, str]] = []
        for directory in ("instructions", "skills", "prompts"):
            root = self._safe_path(directory)
            if not root.exists():
                continue
            for path in sorted(root.rglob("*.md")):
                text = path.read_text(encoding="utf-8")
                if normalized in text.casefold():
                    results.append(
                        {
                            "path": path.relative_to(self.root).as_posix(),
                            "excerpt": self._excerpt(text, normalized),
                        }
                    )
        return results

    def validate(self) -> dict[str, Any]:
        errors: list[str] = []
        try:
            manifest = self.manifest()
            profiles = manifest.get("profiles", {})
            if not isinstance(profiles, dict) or not profiles:
                errors.append("Manifest must define at least one profile")
            else:
                for profile_name in profiles:
                    self.instructions(str(profile_name))
            skill_names = {skill.name for skill in self.skills()}
            runners = manifest.get("runners", {})
            if not isinstance(runners, dict):
                errors.append("Manifest runners must be a mapping")
            else:
                missing = sorted(set(runners) - skill_names)
                if missing:
                    errors.append(f"Runners reference unknown skills: {', '.join(missing)}")
        except (RegistryError, OSError, yaml.YAMLError) as exc:
            errors.append(str(exc))
        return {"valid": not errors, "errors": errors}

    @staticmethod
    def _frontmatter(text: str, path: Path) -> dict[str, Any]:
        if not text.startswith("---\n"):
            raise RegistryError(f"Skill is missing YAML frontmatter: {path}")
        end = text.find("\n---\n", 4)
        if end == -1:
            raise RegistryError(f"Skill frontmatter is not terminated: {path}")
        parsed = yaml.safe_load(text[4:end])
        if not isinstance(parsed, dict):
            raise RegistryError(f"Skill frontmatter must be a mapping: {path}")
        return parsed

    @staticmethod
    def _excerpt(text: str, normalized_query: str, radius: int = 80) -> str:
        normalized_text = text.casefold()
        index = normalized_text.find(normalized_query)
        start = max(0, index - radius)
        end = min(len(text), index + len(normalized_query) + radius)
        return " ".join(text[start:end].split())
