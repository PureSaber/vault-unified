import re
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def test_required_governance_and_usability_files_exist() -> None:
    required = {
        "LICENSE",
        "SECURITY.md",
        "CONTRIBUTING.md",
        "CODE_OF_CONDUCT.md",
        ".github/PULL_REQUEST_TEMPLATE.md",
        ".github/ISSUE_TEMPLATE/bug_report.yml",
        ".github/ISSUE_TEMPLATE/usability_report.yml",
        ".github/ISSUE_TEMPLATE/config.yml",
        "docs/privacy-and-data-boundaries.md",
        "docs/usability-test-plan.md",
        "docs/usability-test-results-template.md",
        "docs/release-readiness-v1.3.md",
    }
    assert {path for path in required if not (REPO_ROOT / path).is_file()} == set()


def test_mit_license_has_repository_owner_and_current_project_year() -> None:
    license_text = _read("LICENSE")
    assert license_text.startswith("MIT License\n")
    assert "Copyright (c) 2026 PureSaber" in license_text
    assert "Permission is hereby granted, free of charge" in license_text


def test_issue_forms_are_parseable_and_enforce_generated_data_confirmation() -> None:
    templates = [
        REPO_ROOT / ".github/ISSUE_TEMPLATE/bug_report.yml",
        REPO_ROOT / ".github/ISSUE_TEMPLATE/usability_report.yml",
    ]
    for template in templates:
        form = yaml.safe_load(template.read_text(encoding="utf-8"))
        assert form["name"]
        assert form["description"]
        checkboxes = [item for item in form["body"] if item["type"] == "checkboxes"]
        assert checkboxes
        labels = " ".join(
            option["label"]
            for item in checkboxes
            for option in item["attributes"]["options"]
        ).lower()
        assert "generated fake data" in labels or "generated data" in labels
        assert all(
            option.get("required") is True
            for item in checkboxes
            for option in item["attributes"]["options"]
        )

    config = yaml.safe_load(
        _read(".github/ISSUE_TEMPLATE/config.yml")
    )
    assert config["blank_issues_enabled"] is False
    assert "security/advisories/new" in config["contact_links"][0]["url"]


def test_feature_freeze_and_human_owner_gates_remain_explicit() -> None:
    pull_request = _read(".github/PULL_REQUEST_TEMPLATE.md")
    for check in (
        "- [ ] 本 PR 不增加新密码源",
        "- [ ] 本 PR 不增加新条目类型",
        "- [ ] 本 PR 不削弱现有安全边界",
        "- [ ] 本 PR 只使用生成的虚假测试数据",
    ):
        assert check in pull_request

    owner_gate = "- [ ] Repository owner reviewed real novice usability results"
    assert owner_gate in pull_request
    assert owner_gate in _read("docs/usability-test-plan.md")
    assert owner_gate in _read("docs/usability-test-results-template.md")
    assert owner_gate in _read("docs/release-readiness-v1.3.md")
    assert "- [x] Repository owner reviewed real novice usability results" not in "\n".join(
        (
            pull_request,
            _read("docs/usability-test-plan.md"),
            _read("docs/usability-test-results-template.md"),
            _read("docs/release-readiness-v1.3.md"),
        )
    )


def test_readme_is_installer_first_and_defers_developer_setup() -> None:
    readme = _read("README.md")
    developer_start = readme.index("## 面向开发者")
    beginner_content = readme[:developer_start]
    assert beginner_content.index("最新版本下载页") < beginner_content.index("创建保险库")
    assert beginner_content.index("创建保险库") < beginner_content.index("添加第一条密码")
    assert beginner_content.index("添加第一条密码") < beginner_content.index("设置备份")
    assert beginner_content.index("设置备份") < beginner_content.index("安装浏览器扩展")
    for term in (
        "setup.ps1",
        "npm ci",
        "pip install",
        "sidecar",
        "Argon2id",
        "AES-GCM",
        "tombstone",
        "local_atomic",
        "Share ID",
    ):
        assert term not in beginner_content


def test_new_governance_markdown_has_no_broken_relative_links() -> None:
    documents = [
        "README.md",
        "SECURITY.md",
        "CONTRIBUTING.md",
        "CODE_OF_CONDUCT.md",
        "docs/privacy-and-data-boundaries.md",
        "docs/usability-test-plan.md",
        "docs/usability-test-results-template.md",
        "docs/release-readiness-v1.3.md",
    ]
    broken: list[str] = []
    for relative in documents:
        source = REPO_ROOT / relative
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", _read(relative)):
            if "://" in target or target.startswith("#"):
                continue
            destination = (source.parent / target.split("#", 1)[0]).resolve()
            if not destination.exists():
                broken.append(f"{relative} -> {target}")
    assert broken == []
