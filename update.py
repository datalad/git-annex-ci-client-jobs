#!/usr/bin/env python3
from enum import Enum
import json
from pathlib import Path
import re
from typing import Any, Dict, Tuple
import click
from pydantic import BaseModel, parse_obj_as
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


status_colors = {
    Status.PASSING: "success",
    Status.FAILING: "critical",
    Status.UNKNOWN: "inactive",
}


class ClientStatus(BaseModel):
    highest_build: int
    tests: Dict[str, Status]


@click.command()
@click.argument("result_branch")
@click.argument(
    "rcfiles", nargs=-1, type=click.Path(exists=True, dir_okay=False, path_type=Path)
)
def main(result_branch: str, rcfiles: Tuple[Path, ...]) -> None:
    m = re.fullmatch(r"result-(.+)-(\d+)", result_branch)
    if not m:
        raise ValueError(f"Invalid result branch name: {result_branch!r}")
    clientid = m[1]
    buildno = int(m[2])
    rcs = {f.stem: int(f.read_text()) for f in rcfiles}
    with STATUS_FILE.open() as fp:
        data = json.load(fp)
    status = parse_obj_as(Dict[str, ClientStatus], data)
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
    with STATUS_FILE.open("w") as fp:
        json.dump(status, fp, indent=4, default=default_json)
        print(file=fp)
    client_status = Status.UNKNOWN
    for st in client.tests.values():
        if st is Status.PASSING:
            client_status = st
        elif st is Status.FAILING:
            client_status = st
            break
    with requests.Session() as s:
        download_badge(
            s,
            BADGE_DIR / f"{clientid}.svg",
            "Tests",
            client_status.value,
            status_colors[client_status],
        )
        for test, st in client.tests.items():
            download_badge(
                s,
                BADGE_DIR / clientid / f"{test}.svg",
                test,
                st.value,
                status_colors[st],
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


def default_json(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.dict()
    elif isinstance(obj, Enum):
        return obj.value
    else:
        return obj


if __name__ == "__main__":
    main()
