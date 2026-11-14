"""Hosted mode's secret files (design 11.5, 12.1): a `file:` reference resolves only inside the secrets folder."""

import yaml

from engine import deploy_checks
from engine.cli import main
from tests.conftest import add_example_account


def _hosted_with_secret(workspace, where: str, secrets_dir: str | None = None):
    path = workspace.config_dir / "ai.yaml"
    ai = yaml.safe_load(path.read_text())
    real, _model, _name = add_example_account(ai)
    ai["providers"][real]["auth"] = f"file:{where}"
    path.write_text(yaml.safe_dump(ai))
    server = workspace.config_dir / "server.yaml"
    data = yaml.safe_load(server.read_text())
    data["mode"] = "hosted"
    if secrets_dir:
        data["secrets_dir"] = secrets_dir
    server.write_text(yaml.safe_dump(data))
    return workspace.config(env={})


def test_a_file_outside_the_secrets_folder_is_refused_in_words(workspace, tmp_path):
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("a-secret-value")
    cfg = _hosted_with_secret(workspace, str(outside))
    found = deploy_checks.run(workspace, cfg)
    assert len(found) == 1 and "isn't in the secrets folder" in found[0] and "a-secret-value" not in found[0]


def test_a_file_inside_the_default_secrets_folder_passes(workspace):
    folder = deploy_checks.secrets_dir(workspace, workspace.config(env={}))
    assert folder == workspace.private_dir / "secrets"
    cfg = _hosted_with_secret(workspace, str(folder / "key.txt"))
    assert deploy_checks.run(workspace, cfg) == []


def test_a_configured_folder_is_the_one_that_counts(workspace, tmp_path):
    folder = tmp_path / "mounted"
    cfg = _hosted_with_secret(workspace, str(folder / "key.txt"), str(folder))
    assert deploy_checks.run(workspace, cfg) == []


def test_a_path_that_climbs_out_or_goes_through_a_link_is_outside(workspace, tmp_path):
    folder = workspace.private_dir / "secrets"
    folder.mkdir(parents=True)
    cfg = _hosted_with_secret(workspace, f"{folder}/../../outside.txt")
    assert deploy_checks.run(workspace, cfg)
    target = tmp_path / "real.txt"
    target.write_text("x")
    (folder / "link.txt").symlink_to(target)
    cfg = _hosted_with_secret(workspace, str(folder / "link.txt"))
    assert deploy_checks.run(workspace, cfg)


def test_serve_in_hosted_mode_stops_on_the_check_before_anything_else(workspace, tmp_path, capsys):
    _hosted_with_secret(workspace, str(tmp_path / "elsewhere.txt"))
    assert main(["serve", "-w", str(workspace.root)]) == 1
    assert "isn't in the secrets folder" in capsys.readouterr().err
