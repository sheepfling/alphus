# Executable argparse output regression

`command.py` is trusted synthetic code, executed by
`tests/gates/review/test_argparse_output_regression.py` with an isolated temporary
working directory. Tests assert the complete directory contents and output file
payload, including absence of every nonselected destination. No consumer source
is imported or executed.

For manual reproduction in an empty temporary directory:

```sh
/path/to/python /path/to/command.py simple broken --output requested.txt render
# Writes child-default.txt, not requested.txt.
/path/to/python /path/to/command.py simple fixed --output requested.txt render
# Writes requested.txt.
```

The fixture's first two arguments select a scenario and declaration variant.
`fixed` means the child action declares `default=argparse.SUPPRESS`; it is **not**
a promise of corrected precedence when a parser-level default exists. For simple
and nested duplicate options this preserves earlier explicit options, preserves
the root default when all options are omitted, and allows later explicit options
to win. Different option strings with the same custom destination collide too.
An implicit `None` child default can silently prevent output entirely.

`set_defaults` is deliberately covered before and after `add_argument`:

- An ordinary explicit action default overrides an earlier parser default.
- An action with `default=argparse.SUPPRESS` does not erase an earlier parser
  default. The parser still installs its default into the child namespace.
- Later `set_defaults` changes existing action defaults, including a previously
  suppressed default.
- Calling `set_defaults(output_path=argparse.SUPPRESS)` is not a safe reset.
  Parser-level defaults still install the literal sentinel string, and this
  fixture writes a file named `==SUPPRESS==`.
- Explicit child values win over parser defaults in every tested ordering.

A command-specific default can intentionally override a global option. A required
child option must be present after the command: a root option cannot satisfy it,
and an error must create no output. These are legitimate reasons not to apply a
blanket SUPPRESS rewrite.

Limits: this matrix exercises ordinary store actions, one selected child (and a
three-level nested path), and relative file paths on the test Python runtime. It
does not establish behavior for custom actions, parser subclasses, parent-parser
reuse, dynamic factories, `parse_intermixed_args`, or arbitrary consumer code.
