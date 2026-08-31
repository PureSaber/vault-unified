from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_feature_freeze_and_pull_request_contract_are_present():
    freeze = (ROOT / "docs" / "feature-freeze-v1.3.md").read_text(encoding="utf-8")
    template = (ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md").read_text(
        encoding="utf-8"
    )

    for prohibited in (
        "新增密码管理器来源",
        "新增条目类型",
        "新增移动端协议",
        "新增局域网 API",
        "新增遥测",
        "扩大浏览器扩展权限",
        "隐式、不可逆迁移",
    ):
        assert prohibited in freeze

    for section in (
        "## Summary",
        "## User-visible behavior",
        "## Threat / data-integrity scope",
        "## Tests",
        "## Screenshots or recordings",
        "## Remaining risks",
        "## Rollback instructions",
    ):
        assert section in template

    for checkbox in (
        "- [ ] 本 PR 不增加新密码源",
        "- [ ] 本 PR 不增加新条目类型",
        "- [ ] 本 PR 不削弱现有安全边界",
        "- [ ] 本 PR 只使用生成的虚假测试数据",
    ):
        assert checkbox in template


def test_hardening_plan_preserves_manual_novice_gate():
    plan = (ROOT / "docs" / "usability-hardening-plan.md").read_text(
        encoding="utf-8"
    )
    assert "origin/main@48442fb6ef6e5a9a34887f0115a3713f910cdb12" in plan
    for pull_request in range(10):
        assert f"PR {pull_request}" in plan
    assert "- [ ] Repository owner reviewed real novice usability results" in plan
    assert "Playwright 结果不能替代" in plan
