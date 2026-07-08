#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "sources"
LIST_DIR = ROOT / "lists"

SOURCE_FILES = {
    "ru": SOURCE_DIR / "ru.raw.txt",
    "direct": SOURCE_DIR / "direct.raw.txt",
}

GENERATED_FILES = {
    "ru_glinet": LIST_DIR / "glinet" / "ru.txt",
    "direct_glinet": LIST_DIR / "glinet" / "direct.txt",
    "ru_compact_glinet": LIST_DIR / "glinet" / "ru.compact.txt",
    "ru_dnsmasq_ipset": LIST_DIR / "dnsmasq" / "ru.ipset.conf",
    "manifest": LIST_DIR / "meta" / "manifest.json",
    "checksums": LIST_DIR / "meta" / "checksums.txt",
}

DOMAIN_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
COMMENT_PREFIXES = ("#", ";")


@dataclass(frozen=True)
class Entry:
    value: str
    kind: str
    source: str
    line_no: int


class ListError(Exception):
    pass


def strip_raw_line(raw_line: str) -> str | None:
    value = raw_line.strip().lower().rstrip(".")
    if not value:
        return None
    if value.startswith(COMMENT_PREFIXES):
        return None
    return value


def normalize_ip_or_network(value: str) -> tuple[str, str] | None:
    try:
        if "/" in value:
            network = ipaddress.ip_network(value, strict=False)
            if network.version != 4:
                raise ListError("only IPv4 CIDR ranges are supported")
            if not network.is_global:
                raise ListError("non-public IPv4 CIDR ranges are not allowed in public lists")
            return str(network), "cidr"

        address = ipaddress.ip_address(value)
        if address.version != 4:
            raise ListError("only IPv4 addresses are supported")
        if not address.is_global:
            raise ListError("non-public IPv4 addresses are not allowed in public lists")
        return str(address), "ipv4"
    except ValueError:
        if re.fullmatch(r"[0-9./]+", value):
            raise ListError("invalid IPv4 or CIDR entry")
        return None


def normalize_domain(value: str) -> str:
    if "/" in value or ":" in value:
        raise ListError("domains must not contain paths, ports, or URL schemes")
    if any(ch.isspace() for ch in value):
        raise ListError("entries must not contain whitespace")

    try:
        ascii_domain = value.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ListError("invalid IDN domain") from exc

    labels = ascii_domain.split(".")
    if len(labels) < 2:
        raise ListError("domain must contain at least one dot")
    if len(ascii_domain) > 253:
        raise ListError("domain is longer than 253 characters")
    for label in labels:
        if not DOMAIN_LABEL_RE.fullmatch(label):
            raise ListError("invalid domain label")
    return ascii_domain


def normalize_entry(value: str, source: str, line_no: int) -> Entry:
    value = value.strip().lower().rstrip(".")
    ip_or_network = normalize_ip_or_network(value)
    if ip_or_network is not None:
        normalized_value, kind = ip_or_network
        return Entry(normalized_value, kind, source, line_no)

    return Entry(normalize_domain(value), "domain", source, line_no)


def read_entries(path: Path) -> tuple[list[Entry], list[str]]:
    entries: list[Entry] = []
    errors: list[str] = []

    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        value = strip_raw_line(raw_line)
        if value is None:
            continue

        try:
            entries.append(normalize_entry(value, path.relative_to(ROOT).as_posix(), line_no))
        except ListError as exc:
            errors.append(f"{path.relative_to(ROOT)}:{line_no}: {exc}: {raw_line.strip()}")

    return entries, errors


def dedupe_entries(entries: list[Entry]) -> tuple[list[Entry], dict[str, list[Entry]]]:
    seen: dict[str, Entry] = {}
    duplicates: dict[str, list[Entry]] = {}

    for entry in entries:
        if entry.value in seen:
            duplicates.setdefault(entry.value, [seen[entry.value]]).append(entry)
            continue
        seen[entry.value] = entry

    return sorted(seen.values(), key=lambda entry: entry.value), duplicates


def compact_domains(entries: list[Entry]) -> list[Entry]:
    domain_values = {entry.value for entry in entries if entry.kind == "domain"}
    compacted: list[Entry] = []

    for entry in entries:
        if entry.kind != "domain":
            compacted.append(entry)
            continue

        labels = entry.value.split(".")
        covered_by_parent = any(".".join(labels[index:]) in domain_values for index in range(1, len(labels) - 1))
        if not covered_by_parent:
            compacted.append(entry)

    return compacted


def serialize_plain(entries: list[Entry]) -> str:
    values = [entry.value for entry in entries]
    return "\n".join(values) + ("\n" if values else "")


def serialize_dnsmasq_ipset(entries: list[Entry], ipset_name: str) -> str:
    domains = [entry.value for entry in entries if entry.kind == "domain"]
    lines = [f"ipset=/{domain}/{ipset_name}" for domain in domains]
    return "\n".join(lines) + ("\n" if lines else "")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_outputs() -> tuple[dict[Path, str], dict[str, object], list[str]]:
    all_errors: list[str] = []
    lists: dict[str, list[Entry]] = {}
    duplicates: dict[str, dict[str, list[Entry]]] = {}

    for list_name, source_path in SOURCE_FILES.items():
        entries, errors = read_entries(source_path)
        all_errors.extend(errors)
        unique_entries, duplicate_entries = dedupe_entries(entries)
        lists[list_name] = unique_entries
        duplicates[list_name] = duplicate_entries

    if all_errors:
        return {}, {}, all_errors

    ru_compact = compact_domains(lists["ru"])

    outputs: dict[Path, str] = {
        GENERATED_FILES["ru_glinet"]: serialize_plain(lists["ru"]),
        GENERATED_FILES["direct_glinet"]: serialize_plain(lists["direct"]),
        GENERATED_FILES["ru_compact_glinet"]: serialize_plain(ru_compact),
        GENERATED_FILES["ru_dnsmasq_ipset"]: serialize_dnsmasq_ipset(lists["ru"], "ru_domains"),
    }

    manifest = {
        "schema": 1,
        "sources": {name: path.relative_to(ROOT).as_posix() for name, path in SOURCE_FILES.items()},
        "outputs": {name: path.relative_to(ROOT).as_posix() for name, path in GENERATED_FILES.items()},
        "lists": {
            name: {
                "total": len(entries),
                "domains": sum(1 for entry in entries if entry.kind == "domain"),
                "ipv4": sum(1 for entry in entries if entry.kind == "ipv4"),
                "cidr": sum(1 for entry in entries if entry.kind == "cidr"),
                "duplicates_removed": sum(len(items) - 1 for items in duplicates[name].values()),
            }
            for name, entries in lists.items()
        },
        "compact": {
            "ru": {
                "total": len(ru_compact),
                "removed_by_parent_domain": len(lists["ru"]) - len(ru_compact),
            }
        },
    }

    manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    outputs[GENERATED_FILES["manifest"]] = manifest_text

    checksum_lines = [
        f"{sha256_text(text)}  {path.relative_to(ROOT).as_posix()}"
        for path, text in sorted(outputs.items(), key=lambda item: item[0].as_posix())
        if path != GENERATED_FILES["checksums"]
    ]
    outputs[GENERATED_FILES["checksums"]] = "\n".join(checksum_lines) + "\n"

    return outputs, manifest, []


def write_outputs(outputs: dict[Path, str]) -> None:
    for path, text in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def check_outputs(outputs: dict[Path, str]) -> list[str]:
    errors: list[str] = []
    for path, expected in outputs.items():
        if not path.exists():
            errors.append(f"missing generated file: {path.relative_to(ROOT)}")
            continue
        actual = path.read_text(encoding="utf-8")
        if actual != expected:
            errors.append(f"stale generated file: {path.relative_to(ROOT)}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Build GL.iNet split-routing list artifacts.")
    parser.add_argument("--check", action="store_true", help="verify generated files without writing")
    args = parser.parse_args()

    outputs, manifest, errors = build_outputs()
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1

    if args.check:
        check_errors = check_outputs(outputs)
        if check_errors:
            print("\n".join(check_errors), file=sys.stderr)
            return 1
    else:
        write_outputs(outputs)

    print(json.dumps(manifest["lists"], indent=2, sort_keys=True))
    print(json.dumps(manifest["compact"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
