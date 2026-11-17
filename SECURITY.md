# Security policy

## Supported versions

Fixes go into the latest release on PyPI; please update before
reporting (`pip install -U crashmetrics`).

| Version | Supported |
| --- | --- |
| Latest minor release | Yes |
| Older releases | No |

## Reporting a problem

Please **do not open a public issue** for a security problem. Report it
privately through GitHub:
[Security → Report a vulnerability](https://github.com/vsk1729/crashmetrics/security/advisories/new).

Include the version, what you found, and a minimal way to show it. You
can expect a first answer within a week; once a fix is released, the
advisory is published with credit to you if you wish.

## What counts

crashmetrics reads files people receive from others: LS-DYNA keyword
decks, binout and ASCII output, ISO-MME data, CSV and Excel files.
Problems such as a crafted file that makes a reader run code, write
outside its output folder, or use unbounded memory or time are security
problems. The package never runs code from the files it reads (keyword
parameter expressions are evaluated without `eval`).

A wrong engineering result is not a security problem; please report it
as a bug or a protocol correction. And remember that crashmetrics is an
engineering aid: results must be checked before they are used for design
or certification decisions (see the disclaimer).
