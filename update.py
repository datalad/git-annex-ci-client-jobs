#!/usr/bin/env python3
from __future__ import annotations
from enum import Enum
import json
from pathlib import Path
import re
from typing import Dict
import click
from pydantic import BaseModel, TypeAdapter
import requests

BADGE_DIR = Path(__file__).with_name("badges")
STATUS_FILE = Path(__file__).with_name("status.json")


class Status(Enum):
    PASSING = "passing"
    FAILING = "failing"
    UNKNOWN = "unknown"

    @classmethod
    def from_rc(cls, rc: int) -> "Status":
        return cls.PASSING if rc == 0 else cls.FAILING

    @property
    def color(self) -> str:
        if self is Status.PASSING:
            return "success"
        elif self is Status.FAILING:
            return "critical"
        elif self is Status.UNKNOWN:
            return "inactive"
        else:
            raise AssertionError(f"Unhandled Status member: {self!r}")


class ClientStatus(BaseModel):
    highest_build: int
    tests: Dict[str, Status]

    def get_status(self) -> Status:
        status = Status.UNKNOWN
        for st in self.tests.values():
            if st is Status.PASSING:
                status = st
            elif st is Status.FAILING:
                status = st
                break
        return status


@click.command()
@click.argument("result_branch")
@click.argument(
    "rcfiles", nargs=-1, type=click.Path(exists=True, dir_okay=False, path_type=Path)
)
def main(result_branch: str, rcfiles: tuple[Path, ...]) -> None:
    m = re.fullmatch(r"result-(.+)-(\d+)", result_branch)
    if not m:
        raise ValueError(f"Invalid result branch name: {result_branch!r}")
    clientid = m[1]
    buildno = int(m[2])
    rcs = {f.stem: int(f.read_text()) for f in rcfiles}
    with STATUS_FILE.open() as fp:
        data = json.load(fp)
    adapter = TypeAdapter(Dict[str, ClientStatus])
    status = adapter.validate_python(data)
    try:
        client = status[clientid]
    except KeyError:
        client = status[clientid] = ClientStatus(
            highest_build=buildno,
            tests={k: Status.from_rc(v) for k, v in rcs.items()},
        )
    else:
        if buildno <= client.highest_build:
            # Print a message?
            return
        client.highest_build = buildno
        unupdated = set(client.tests.keys())
        for test, rc in rcs.items():
            client.tests[test] = Status.from_rc(rc)
            unupdated.discard(test)
        for test in unupdated:
            client.tests[test] = Status.UNKNOWN
    STATUS_FILE.write_bytes(adapter.dump_json(status, indent=4) + b"\n")
    client_status = client.get_status()
    global_status = Status.UNKNOWN
    for cl in status.values():
        st = cl.get_status()
        if st is Status.PASSING:
            global_status = st
        elif st is Status.FAILING:
            global_status = st
            break
    with requests.Session() as s:
        download_badge(
            s,
            BADGE_DIR / ".all-clients.svg",
            "Tests on Clients",
            global_status.value,
            global_status.color,
        )
        download_badge(
            s,
            BADGE_DIR / f"{clientid}.svg",
            "Tests",
            client_status.value,
            client_status.color,
        )
        for test, st in client.tests.items():
            download_badge(
                s,
                BADGE_DIR / clientid / f"{test}.svg",
                test,
                st.value,
                st.color,
            )


def download_badge(
    s: requests.Session, path: Path, label: str, message: str, color: str
) -> None:
    r = s.get(
        "https://img.shields.io/static/v1",
        params={"label": label, "message": message, "color": color},
    )
    r.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(r.content)


if __name__ == "__main__":
    main()
