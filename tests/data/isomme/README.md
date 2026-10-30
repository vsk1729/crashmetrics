# ISO-MME test data

From [jonaskeller14/pyisomme](https://github.com/jonaskeller14/pyisomme),
commit `8d878af4908fa70eb3c7402c763f163ae4fe5a9b`, MIT licence (see
`LICENSE`, Copyright (c) 2024 Jonas Keller): unchanged copies of
`data/tests/ascii/`, `data/tests/windows-1252/` and
`data/tests/utf-8.zip`.

Hand-built ISO-MME 1.6 containers: three channels (time reference,
head CG x acceleration, chest deflection), 20 samples at 10 kHz from
-0.5 ms. They cover a time channel without a time base, an explicit
reference time channel, an implicit time base, one `NOVALUE` sample, a
colon inside a header value, an empty value, tab padding and three text
encodings.
