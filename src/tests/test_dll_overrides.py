"""Tests for DLL override generation in mods module."""

from dataclasses import replace
from typing import TYPE_CHECKING
from unittest.mock import patch

from enshctl.mods import DEFAULT_DLL_OVERRIDES, generate_dll_overrides, resolve_dll_overrides
from enshctl.settings import AppSettings

if TYPE_CHECKING:
    from pathlib import Path


def test_default_overrides_constant() -> None:
    assert DEFAULT_DLL_OVERRIDES == "mscoree,mshtml="


def test_no_dlls(tmp_path: Path) -> None:
    result = generate_dll_overrides(tmp_path)
    assert result == "mscoree,mshtml="


def test_win_prefix_dll(tmp_path: Path) -> None:
    (tmp_path / "winhttp.dll").touch()
    result = generate_dll_overrides(tmp_path)
    assert result == "mscoree,mshtml=,winhttp=n,b"


def test_non_prefix_dll(tmp_path: Path) -> None:
    (tmp_path / "dinput8.dll").touch()
    result = generate_dll_overrides(tmp_path)
    assert result == "mscoree,mshtml=,dinput8=n"


def test_mixed_dlls(tmp_path: Path) -> None:
    (tmp_path / "winhttp.dll").touch()
    (tmp_path / "dinput8.dll").touch()
    result = generate_dll_overrides(tmp_path)
    assert result == "mscoree,mshtml=,dinput8=n,winhttp=n,b"


def test_nested_subdirectory_dll(tmp_path: Path) -> None:
    subdir = tmp_path / "Engine" / "Binaries" / "ThirdParty"
    subdir.mkdir(parents=True)
    (subdir / "winmm.dll").touch()
    result = generate_dll_overrides(tmp_path)
    assert result == "mscoree,mshtml=,winmm=n,b"


def test_case_insensitive_extension(tmp_path: Path) -> None:
    (tmp_path / "mylib.DLL").touch()
    (tmp_path / "another.Dll").touch()
    result = generate_dll_overrides(tmp_path)
    assert "mylib=n" in result
    assert "another=n" in result


def test_win_prefix_case_insensitive(tmp_path: Path) -> None:
    (tmp_path / "WinHTTP.dll").touch()
    (tmp_path / "WINMM.DLL").touch()
    result = generate_dll_overrides(tmp_path)
    assert "winhttp=n,b" in result
    assert "winmm=n,b" in result


def test_non_dll_files_ignored(tmp_path: Path) -> None:
    (tmp_path / "readme.txt").touch()
    (tmp_path / "config.json").touch()
    (tmp_path / "mylib.dll").touch()
    result = generate_dll_overrides(tmp_path)
    assert result == "mscoree,mshtml=,mylib=n"


def test_empty_mod_overlay_dir(tmp_path: Path) -> None:
    result = generate_dll_overrides(tmp_path)
    assert result == "mscoree,mshtml="


def test_nonexistent_mod_overlay_dir(tmp_path: Path) -> None:
    nonexistent = tmp_path / "does_not_exist"
    result = generate_dll_overrides(nonexistent)
    assert result == "mscoree,mshtml="


def test_resolve_dll_overrides_uses_user_value() -> None:
    # GIVEN an explicit WINEDLLOVERRIDES setting
    settings = replace(AppSettings(), winedlloverrides="dinput8=n")

    # WHEN resolving overrides
    # THEN the settings value wins verbatim over generation
    with patch("enshctl.mods.generate_dll_overrides", side_effect=AssertionError("must not generate")):
        assert resolve_dll_overrides(settings) == "dinput8=n"


def test_resolve_dll_overrides_preserves_empty_value() -> None:
    # GIVEN an explicitly empty WINEDLLOVERRIDES setting
    settings = replace(AppSettings(), winedlloverrides="")

    # WHEN resolving overrides
    # THEN the empty value passes through instead of generating overrides
    assert resolve_dll_overrides(settings) == ""


def test_resolve_dll_overrides_preserves_whitespace_value() -> None:
    # GIVEN a whitespace-only WINEDLLOVERRIDES setting
    settings = replace(AppSettings(), winedlloverrides="   ")

    # WHEN resolving overrides
    # THEN the whitespace value passes through instead of generating overrides
    assert resolve_dll_overrides(settings) == "   "


def test_resolve_dll_overrides_generates_when_unset() -> None:
    # GIVEN winedlloverrides unset
    settings = replace(AppSettings(), winedlloverrides=None)

    # WHEN resolving overrides
    # THEN generated overrides apply
    with patch("enshctl.mods.generate_dll_overrides", return_value="mscoree,mshtml=,mylib=n") as mock_generate:
        assert resolve_dll_overrides(settings) == "mscoree,mshtml=,mylib=n"
    mock_generate.assert_called_once_with()
