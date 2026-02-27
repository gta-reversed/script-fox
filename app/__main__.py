import io
from pathlib import Path
from pprint import pprint
import re
import logging
from typing import cast

from . import util
from .data import DEFINITIONS
from .writers import (
    write_docs,
    write_handler_function_stub,
    write_register_handler,
)
from .args import args
from .jsontypes import Command

logger = logging.getLogger(__name__)


def update_existing(commands_by_criteria: list[Command]):
    """
    Update existing file (handles case when args.input is provided)
    """

    all_commands = [
        command
        for extension in DEFINITIONS["extensions"]
        for command in extension["commands"]
    ]
    commands_by_name = {cmd["name"]: cmd for cmd in all_commands}

    with Path(args.input).open("r+", encoding="utf-8") as f:
        lines = f.readlines()

    with Path(args.output or args.input).open("w", encoding="utf-8") as f:
        # Find where `RegisterHandlers` is
        # We assume it's at the end of the file, if not, the code below won't work all that good...
        register_handlers_line_index = next(
            (
                i
                for i, line in enumerate(lines)
                if line.find("RegisterHandlers()") != -1
            ),
            -1,
        )
        if register_handlers_line_index == -1:
            raise NotImplementedError(
                "Could not find `RegisterHandlers()` function in the input file - cannot add missing handlers"
            ) from None

        # Find all already registered handlers in the file to avoid adding duplicate registrations/stubs
        # It matches on commented out register lines as well
        register_handler_macros_regex = re.compile(
            r"^\s*(\/\/)?\s*(?P<macro>"
            + "|".join(
                (
                    "REGISTER_COMMAND_HANDLER",
                    "REGISTER_UNSUPPORTED_COMMAND_HANDLER",
                    "REGISTER_COMMAND_NOP",
                    "REGISTER_COMMAND_UNIMPLEMENTED",
                )
            )
            + r")\s*\(\s*COMMAND_(?P<command_name>[A-Za-z0-9_]+)\s*(?:,\s*(?P<handler>[A-Za-z0-9_]+))?\s*\)\s*;"
        )
        register_call_by_command = {
            cast(str, match.group("command_name")): (  # No COMMAND_ prefix
                cast(str | None, match.group("handler")),
                cast(str, match.group("macro")),
            )
            for line in lines
            if (match := register_handler_macros_regex.match(line.strip()))
        }
        # pprint(register_call_by_command)

        commands_by_handler_name = {
            handler_name.lower(): cmd
            for cmd in all_commands
            if (handler_name := util.get_handler_name(cmd))
        }

        # Find commands that match the criteria but don't have a handler registered
        missing_register_handler_commands = [
            commands_by_name[cmd_name]
            for cmd_name in set(cmd["name"] for cmd in commands_by_criteria).difference(
                set(register_call_by_command.keys())
            )
        ]

        # Old-style single-line docs comment regex (e.g. `// COMMAND_FOO` or `/// COMMAND_FOO - some description` with or without the `COMMAND_` prefix)
        singleline_docs_comment_regex = re.compile(
            rf"^\s*//+\s*(?P<command_name>[COMMAND_]?{'|'.join(cmd for cmd in register_call_by_command.keys())})(?:\s*-\s*(?P<description>.*))?$"
        )

        # Handler function regex - matches function definitions that look like command handlers
        # Don't want to match only to known handlers though so we can print warnings for handlers that we can't resolve to any command in the definitions
        cpp_function_regex = re.compile(
            r"^\s*(?!if)(?P<return_type>[A-Za-z0-9_<>,\s:]+)\s+(?!constexpr)(?P<handler_name>[a-zA-Z_][a-zA-Z0-9_]*)\s*\((?P<params>[^)]*)\)\s*{\s*$",
            re.IGNORECASE,
        )

        # Check if line should be written as-is, or needs to be replaced by new docs comment
        def get_line_info(
            line: str,
        ) -> tuple[Command, bool] | tuple[None, None]:
            # Handle old-style single-line docs comments and replace them with new-style
            if match := singleline_docs_comment_regex.match(line):
                command_name = match.group("command_name").removeprefix("COMMAND_")
                command = commands_by_name.get(command_name)

                if command:
                    return command, True

                logger.warning(
                    "Command `%s` found in docs comment but not in definitions, skipping doc generation for it",
                    command_name,
                )

            # Try matching to a function
            elif match := cpp_function_regex.match(line):
                handler_name = match.group("handler_name")
                command = commands_by_handler_name.get(handler_name.lower())

                if command:
                    return command, False

                logger.warning(
                    "Can't resolve function `%s` to any command in definitions, skipping doc generation for it",
                    handler_name,
                )

            return None, None

        # Keep track of handlers we've already added docs for
        has_docs_commands = set()
        handlers_found = set()
        
        # New style docs comment regex
        new_style_docs_comment_regex = re.compile(
            r"@command\s+(?P<command>[A-Za-z0-9_]+)"
        )

        # Add docs to handlers
        for v in lines[:register_handlers_line_index]:
            stripped_line = v.strip()

            # Process new-style docs comments
            if match := new_style_docs_comment_regex.search(stripped_line):
                has_docs_commands.add(match.group("command"))

            command, replace_line = get_line_info(stripped_line)
            if command:
                handlers_found.add(command["name"])
                if command["name"] not in has_docs_commands:
                    write_docs(f, command)
                    has_docs_commands.add(command["name"])
                    if replace_line:
                        continue

            f.write(v)

        logger.info("Added missing docs to %i handlers", len(has_docs_commands))

        # Add missing stubs (after existing handlers but before the `RegisterHandlers` function)
        for cmd in missing_register_handler_commands:
            if cmd["name"] in handlers_found:
                continue
            write_docs(f, cmd)
            write_handler_function_stub(f, cmd)
            f.write("\n")

        # Write the line with `RegisterHandlers()` function declaration and `REGISTER_COMMAND_HANDLER_BEGIN` before adding new handlers
        register_command_handler_begin_line_index = next(
            (
                i
                for i, line in enumerate(lines)
                if line.find("REGISTER_COMMAND_HANDLER_BEGIN") != -1
            ),
            -1,
        )
        if register_command_handler_begin_line_index == -1:
            raise NotImplementedError(
                "Could not find `REGISTER_COMMAND_HANDLER_BEGIN` in the input file - cannot add missing handlers"
            ) from None
        for v in lines[
            register_handlers_line_index : register_command_handler_begin_line_index + 1
        ]:
            f.write(v)

        # Add missing register handler calls
        # They're written in groups - regular, nops, unsupported
        if args.generate_register_calls and missing_register_handler_commands:
            regular_handlers_f, nop_handlers_f, unsupported_handlers_f = (
                io.StringIO(),
                io.StringIO(),
                io.StringIO(),
            )

            def get_file_for_command(cmd: Command):
                if attrs := cmd.get("attrs", None):
                    if attrs.get(
                        "is_unsupported"
                    ):  # This should be before the nop handler, since some commands can be both unsupported and nop, but we want to prioritize unsupported in that case
                        return unsupported_handlers_f

                    if attrs.get("is_nop", False):
                        return nop_handlers_f

                return regular_handlers_f

            for cmd in missing_register_handler_commands:
                write_register_handler(get_file_for_command(cmd), cmd)

            # Write these back into the file in the correct order
            for handlers_f in [
                regular_handlers_f,
                nop_handlers_f,
                unsupported_handlers_f,
            ]:
                if content := handlers_f.getvalue():  # maybe seek?
                    f.write("\n")
                    f.write(content)

            logger.info(
                "Added missing handlers for %i commands",
                len(missing_register_handler_commands),
            )

        # Write rest of the file as-is
        for v in lines[register_command_handler_begin_line_index + 1 :]:
            f.write(v)

    logger.info("Added missing docs and stubs to `%s`", args.input)


def generate_new(commands_by_criteria: list[Command]):
    output_path = Path(args.output or Path.cwd() / "output.cpp")

    # Write stubs
    with output_path.open("w", encoding="utf-8") as f:
        for cmd in commands_by_criteria:
            if cmd.get("attrs", {}).get("is_nop", False):
                logger.warning(
                    "No stub will be generated for command %s (%s) since it is marked as a no-op",
                    cmd["name"],
                    cmd["id"],
                )
                continue

            write_docs(f, cmd)
            write_handler_function_stub(f, cmd)
            f.write("\n")

    # Write handlers
    with output_path.with_stem(f"{output_path.stem}.handlers").open(
        "w", encoding="utf-8"
    ) as f:
        if args.generate_register_calls:
            # Separately generate handlers and nops to group them together in the output
            for is_nop in [
                False,
                True,
            ]:
                for cmd in commands_by_criteria:
                    if cmd.get("attrs", {}).get("is_nop", False) == is_nop:
                        write_register_handler(f, cmd)

    logger.info(
        "Processed %i commands to `%s`",
        len(commands_by_criteria),
        output_path.absolute(),
    )


def main():
    # Gather commands matching the specified criteria (extension, command name pattern, class name pattern, etc...)
    commands = [
        command
        for extension in DEFINITIONS["extensions"]
        if not args.extension or re.search(args.extension, extension["name"])
        for command in extension["commands"]
        if re.search(args.name, command["name"])
        and (
            not args.klass
            or ("class" in command and re.search(args.klass, command["class"]))
        )
    ]
    if not commands:
        return logger.error("No commands matched the given criteria")

    if args.input:
        update_existing(commands)
    else:
        generate_new(commands)


if __name__ == "__main__":
    main()
