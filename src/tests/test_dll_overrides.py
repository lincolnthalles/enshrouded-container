"""Tests for DLL override generation in mods module."""

from typing import TYPE_CHECKING

from enshctl.mods import DEFAULT_DLL_OVERRIDES, generate_dll_overrides

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


def test_empty_mods_dir(tmp_path: Path) -> None:
    result = generate_dll_overrides(tmp_path)
    assert result == "mscoree,mshtml="


def test_nonexistent_mods_dir(tmp_path: Path) -> None:
    nonexistent = tmp_path / "does_not_exist"
    result = generate_dll_overrides(nonexistent)
    assert result == "mscoree,mshtml="
