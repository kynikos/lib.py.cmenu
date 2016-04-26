# cmenu - Command-line interface.
# Copyright (C) 2016 Dario Giovannetti <dev@dariogiovannetti.net>
#
# This file is part of cmenu.
#
# cmenu is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# cmenu is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with cmenu.  If not, see <http://www.gnu.org/licenses/>.

import shlex
import readline
from collections import OrderedDict

# TODO: Test with pexpect

"""
The main differences from cmd.Cmd are:
* Submenus
* Different types of commands: actions, editors, ...
* Command names can use all characters, as they are not defined by the method's
  name
* A command is valid even if only an initial substring is entered, provided
  that it is unique
* The automatic help screen shows each command with a short description
* Dynamic, automatic prompt based on submenus' names
* Additional methods (e.g. loop_lines and loop_test)
* Missing methods (e.g. precmd and postcmd)
* Uses shlex.split by default
"""

SPLIT_ARGS = shlex.split
READLINE_INIT = """
tab: complete
"""


def configure_readline():
    # TODO: A lot more than word completion can be done with readline, see:
    #       https://pymotw.com/2/readline/
    #       https://docs.python.org/3.5/library/readline.html
    #           readline.set_completer_delims(string)
    for line in READLINE_INIT.splitlines():
        readline.parse_and_bind(line)


class DynamicPrompt:
    """
    A _Menu prompt that automatically shows the path of submenus.
    """
    PREFIX = '('
    SEPARATOR = '>'
    SUFFIX = ') '

    def __init__(self, menu):
        self.menu = menu

        path = [self.menu.name]
        parentmenu = self.menu.parentmenu
        while parentmenu:
            path.append(parentmenu.name)
            parentmenu = parentmenu.parentmenu
        self.prompt = ''.join((self.PREFIX,
                               self.SEPARATOR.join(reversed(path)),
                               self.SUFFIX))

    def __str__(self):
        return self.prompt


class _Completer:
    def __init__(self, menu):
        self.menu = menu

        # TODO: Cache the last N requested current_line/matches pairs?
        #       (with collections.deque)
        self.line = None
        self.matches = []

    def complete(self, rl_prefix, rl_index):
        line = readline.get_line_buffer()
        if line != self.line:
            self.line = line
            sp_args = SPLIT_ARGS(line)
            rl_begidx = readline.get_begidx()
            rl_endidx = readline.get_endidx()
            self.matches = self.menu.complete(sp_args, line, rl_prefix,
                                              rl_begidx, rl_endidx)
        try:
            return self.matches[rl_index]
        except IndexError:
            return None


class _Command:
    def __init__(self, parentmenu, name, helpfull, helpshort=None):
        self.parentmenu = parentmenu
        self.name = name
        self.helpfull = helpfull
        # TODO: Initial empty lines should be discarded
        self.helpshort = helpshort or helpfull.split('\n', 1)[0]

        if parentmenu:
            parentmenu.add_command(self)

    def complete(self, sp_args, line, rl_prefix, rl_begidx, rl_endidx):
        """
        Override in order to have command or argument completion.

        It is necessary to return a 'list', i.e. not a tuple or other
        sequences.
        """
        return []

    def help(self, *args):
        """
        Can be overridden (and for example _Menu does).
        """
        if args:
            print('Invalid arguments:', *args)
        else:
            print(self.helpfull)
        return False

    def execute(self, *args):
        """
        Must be overridden.
        """
        raise NotImplementedError()


class _Menu(_Command):
    INHERIT = object()
    END_LOOP = object()

    def __init__(self, parentmenu, name, helpheader, prompt=INHERIT):
        super().__init__(parentmenu, name, helpfull=helpheader)

        try:
            self.prompt = prompt(self)
        except TypeError:
            # Raised if prompt isn't callable, e.g. it's not a DynamicPrompt
            # class
            if prompt is self.INHERIT:
                if parentmenu:
                    try:
                        self.prompt = parentmenu.prompt.__class__(self)
                    except TypeError:
                        # Raised if prompt isn't callable, e.g. it's not a
                        # DynamicPrompt # class
                        self.prompt = parentmenu.prompt
                else:
                    raise InvalidPromptError()
            else:
                self.prompt = prompt

        self.name_to_command = OrderedDict()
        self.completer = _Completer(self)

    def add_command(self, command):
        if command.name not in self.name_to_command:
            self.name_to_command[command.name] = command
        else:
            raise DuplicatedCommandNameError(command.name)

    def _find_commands(self, cmdprefix):
        try:
            # In case there are two command names, one substring of the other,
            # e.g. 'cmd1' and 'cmd10', this method would never only return
            # 'cmd1' if a perfect match is not tested before testing the
            # string against startswith
            return [self.name_to_command[cmdprefix]]
        except KeyError:
            return [command for name, command in self.name_to_command.items()
                    if name.startswith(cmdprefix)]

    def loop_input(self):
        # Always adapt the other self.loop_* methods when making changes to
        # this one

        # Always reset the completer here because it depends on each (sub)menu
        readline.set_completer(self.completer.complete)
        while True:
            cmdline = input(self.prompt)
            if self.run_line(cmdline) is self.END_LOOP:
                break

    def loop_lines(self, cmdlines):
        # Always adapt the other self.loop_* methods when making changes to
        # this one
        for cmdline in cmdlines:
            # TODO: See syncere bug #60
            if self.run_line(cmdline) is self.END_LOOP:
                break

    def loop_test(self, cmdlines):
        # Always adapt the other self.loop_* methods when making changes to
        # this one
        # If cmdlines is empty, the final else clause isn't reached
        if not cmdlines:
            raise InsufficientTestCommands()
        for cmdline in cmdlines:
            # TODO: See syncere bug #60
            print(self.prompt, cmdline, sep='')
            if self.run_line(cmdline) is self.END_LOOP:
                break
        else:
            raise InsufficientTestCommands()

    def run_line(self, cmdline):
        if not cmdline:
            return self.on_empty_line()
        cmdprefix, *args = SPLIT_ARGS(cmdline)
        return self.run_command(cmdprefix, *args)

    def run_command(self, cmdprefix, *args):
        return self._run_command('execute', cmdprefix, *args)

    def _run_command(self, method, cmdprefix, *args):
        cmdmatches = self._find_commands(cmdprefix)
        if len(cmdmatches) == 1:
            return getattr(cmdmatches[0], method)(*args)
        elif args or len(cmdmatches) == 0:
            return self.on_bad_command(cmdprefix, *args)
        else:
            # TODO: Fill the next input with cmdline
            return self.on_ambiguous_command(cmdmatches, cmdprefix, *args)

    def on_empty_line(self):
        # TODO: Conform to the output of
        #       readline.set_completion_display_matches_hook
        #       https://docs.python.org/3.5/library/readline.html
        print(*self.name_to_command.keys())
        return False

    def on_bad_command(self, cmdprefix, *args):
        print('Unrecognized command:', cmdprefix)
        return False

    def on_ambiguous_command(self, cmdmatches, cmdprefix, *args):
        print('Ambiguous command:', cmdprefix,
              '[' + ','.join(cmd.name for cmd in cmdmatches) + ']')
        return False

    def complete(self, sp_args, line, rl_prefix, rl_begidx, rl_endidx):
        # It's necessary to return a 'list', not just any sequence type
        if len(sp_args) == 0:
            return list(self.name_to_command.keys())
        elif len(sp_args) == 1 and line.endswith(sp_args[0]):
            matches = []
            for name in self.name_to_command.keys():
                if name.startswith(sp_args[0]):
                    matches.append(name)
            if len(matches) == 1:
                # In general, SPLIT_ARGS and readline use different word
                #  delimiters, see e.g. the docs for
                #  readline.get_completer_delims()
                # If for example there's a 'foo-bar' command, SPLIT_ARGS sees
                #  it as a single word, but readline by default will split it
                #  in two words, 'foo' and 'bar', and if 'foo-b' is entered in
                #  the command line, and Tab is pressed, the word will be
                #  completed as 'foo-bfoo-bar', unless we compensate here by
                #  subtracting the rl_prefix from the found match
                sub = len(sp_args[0]) - len(rl_prefix)
                return [matches[0][sub:]]
            else:
                return matches
        else:
            # if len(sp_args) == 1 but line.endswith(sp_args[0]) is False, it
            # means that the first sp_args is already complete
            command = self.name_to_command[sp_args[0]]
            return command.complete(sp_args[1:], line, rl_prefix, rl_begidx,
                                    rl_endidx)

    def help(self, *args):
        if args:
            return self._run_command('help', *args)
        else:
            # TODO: Better organize white space
            print(self.helpfull)
            width = max(len(name) for name in self.name_to_command.keys())
            for name, command in self.name_to_command.items():
                print('  {}    {}'.format(name.ljust(width),
                                          command.helpshort))
            return False

    def execute(self, *args):
        if args:
            return self.run_command(*args)
        else:
            return self.loop_input()


class RootMenu(_Menu):
    """
    The class to be used for the main menu of an application.
    """
    def __init__(self, name, helpheader, prompt=DynamicPrompt,
                 readlinecfg=configure_readline):
        readlinecfg()
        super().__init__(None, name, helpheader, prompt)


class SubMenu(_Menu):
    """
    The class to be used for menus under a main menu.
    """
    def __init__(self, parentmenu, name, helpheader, prompt=_Menu.INHERIT):
        super().__init__(parentmenu, name, helpheader, prompt)


class Help(_Command):
    """
    A command that shows a help screen.
    """
    def execute(self, *args):
        return self.parentmenu.help(*args)


class Alias(_Command):
    """
    A command that executes a series of other commands.
    """
    def __init__(self, parentmenu, name, alias):
        super().__init__(parentmenu, name, helpfull="Alias <{}>".format(alias))
        self.alias = SPLIT_ARGS(alias)

    def execute(self, *args):
        return self.parentmenu.run_command(*self.alias, *args)


class Action(_Command):
    """
    A command that executes a function.
    """
    def __init__(self, parentmenu, name, execute, helpfull):
        super().__init__(parentmenu, name, helpfull)
        self.execute = execute


class Question(_Command):
    """
    A command that prompts the user for some input text.
    """
    def execute(self, *args):
        # TODO: Implement
        raise NotImplementedError()


class Choice(_Command):
    """
    A command that prompts the user to choose from a set of answers.
    """
    def execute(self, *args):
        # TODO: Implement
        raise NotImplementedError()


class LineEditor(_Command):
    """
    A command that presents an editable string of text.
    """
    def execute(self, *args):
        # TODO: Implement
        raise NotImplementedError()


class TextEditor(_Command):
    """
    A command that opens text in an external editor.
    """
    def execute(self, *args):
        # TODO: Implement
        raise NotImplementedError()


# TODO: Use a common root exception class once a name for this module is
#       decided
class RenameMeTODO(Exception):
    pass


class DuplicatedCommandNameError(RenameMeTODO):
    pass


class InsufficientTestCommands(RenameMeTODO):
    pass


class InvalidPromptError(RenameMeTODO):
    pass
