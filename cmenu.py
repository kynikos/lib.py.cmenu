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
import inspect
import sys

# TODO: Write documentation
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
INHERIT = object()


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
    def __init__(self, parentmenu, name, helpshort, helpfull):
        self.parentmenu = parentmenu
        self.name = name

        if hasattr(helpfull, '__call__'):
            self.helpfull = inspect.getdoc(helpfull)
        else:
            self.helpfull = helpfull or helpshort or ""

        if helpshort:
            self.helpshort = helpshort
        else:
            for line in self.helpfull.splitlines():
                if line and not line.isspace():
                    self.helpshort = line
                    break
            else:
                self.helpshort = ""

        if parentmenu:
            if name not in self.parentmenu.name_to_command:
                self.parentmenu.name_to_command[name] = self
            else:
                raise DuplicatedCommandNameError(name)

    def uninstall(self):
        del self.parentmenu.name_to_command[self.name]

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

    def execute(self, *args):
        """
        Must be overridden.
        """
        raise NotImplementedError()


class _Menu(_Command):
    HELP_INDENT = 2
    HELP_SPACING = 4
    EndLoops = type('EndLoops', (Exception, ), {})

    def __init__(self, parentmenu, name, helpshort, helpfull, prompt=INHERIT):
        super().__init__(parentmenu, name, helpshort, helpfull)

        try:
            self.prompt = prompt(self)
        except TypeError:
            # Raised if prompt isn't callable, e.g. it's not a DynamicPrompt
            # class
            if prompt is INHERIT:
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

    def get_command(self, name):
        # This can raise KeyError, but it's ok
        return self.name_to_command[name]

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

    def _loop(func):
        def inner(self, *args, **kwargs):
            try:
                func(self, *args, **kwargs)
            except self.EndLoops as exc:
                if self.parentmenu:
                    if exc.args[0] < 2:
                        # Always reset the completer here because it depends on
                        # each (sub)menu
                        readline.set_completer(
                                            self.parentmenu.completer.complete)
                    else:
                        raise self.EndLoops(exc.args[0] - 1)
        return inner

    @_loop
    def loop_input(self):
        # Always adapt the other self.loop_* methods when making changes to
        # this one

        # Always reset the completer here because it depends on each (sub)menu
        readline.set_completer(self.completer.complete)
        while True:
            cmdline = input(self.prompt)
            self.run_line(cmdline)

    @_loop
    def loop_lines(self, cmdlines):
        # Always adapt the other self.loop_* methods when making changes to
        # this one

        for cmdline in cmdlines:
            # TODO: Support a cmdline value of True (or another non-string)
            #       to allow entering a command interactively through a normal
            #       input prompt; maybe a new special command class should also
            #       be added to resume the execution of the 'cmdline' list
            #       (e.g. 'T: resume the testing commands list')
            self.run_line(cmdline)

    @_loop
    def loop_test(self, cmdlines):
        # Always adapt the other self.loop_* methods when making changes to
        # this one

        # If cmdlines is empty, the final else clause isn't reached
        if not cmdlines:
            raise InsufficientTestCommands()
        for cmdline in cmdlines:
            # See TODO above in loop_lines
            print(self.prompt, cmdline, sep='')
            self.run_line(cmdline)
        else:
            raise InsufficientTestCommands()

    def run_line(self, cmdline):
        if not cmdline:
            self.on_empty_line()
        else:
            cmdprefix, *args = SPLIT_ARGS(cmdline)
            self.run_command(cmdprefix, *args)

    def run_command(self, cmdprefix, *args):
        self._run_command('execute', cmdprefix, *args)

    def _run_command(self, method, cmdprefix, *args):
        cmdmatches = self._find_commands(cmdprefix)
        if len(cmdmatches) == 1:
            getattr(cmdmatches[0], method)(*args)
        elif len(cmdmatches) == 0:
            self.on_bad_command(cmdprefix, *args)
        else:
            self.on_ambiguous_command(cmdmatches, cmdprefix, *args)

    def on_empty_line(self):
        # TODO: Optionally print a list of the available comands
        #       Conform to the output of
        #       readline.set_completion_display_matches_hook
        #       https://docs.python.org/3.5/library/readline.html
        # print(*self.name_to_command.keys())
        pass

    def on_bad_command(self, cmdprefix, *args):
        print('Unrecognized command:', cmdprefix)

    def on_ambiguous_command(self, cmdmatches, cmdprefix, *args):
        # TODO: Fill the next input with cmdline (maybe raise a special
        #       exception, similar to the EndLoops, that is used to prefill
        #       the next input)
        print('Ambiguous command:', cmdprefix,
              '[' + ','.join(cmd.name for cmd in cmdmatches) + ']')

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
            matches = self._find_commands(sp_args[0])
            if len(matches) == 1:
                return matches[0].complete(sp_args[1:], line, rl_prefix,
                                           rl_begidx, rl_endidx)
            else:
                return []

    def help(self, *args):
        if args:
            self._run_command('help', *args)
        else:
            width = max(len(name) for name in self.name_to_command.keys())
            # TODO: Optionally print the aliases in a separate table
            command_list = ['{0}{1}{2}{3}'.format(' ' * self.HELP_INDENT,
                                                  name.ljust(width),
                                                  ' ' * self.HELP_SPACING,
                                                  command.helpshort)
                            for name, command in self.name_to_command.items()]
            print(self.helpfull.format(command_list='\n'.join(command_list)))

    def execute(self, *args):
        if args:
            self.run_command(*args)
        else:
            self.loop_input()


class RootMenu(_Menu):
    """
    The class to be used for the main menu of an application.
    """
    def __init__(self, name, helpshort=None, helpfull=None,
                 prompt=DynamicPrompt, readlinecfg=configure_readline):
        readlinecfg()
        super().__init__(None, name, helpshort, helpfull, prompt)


class SubMenu(_Menu):
    """
    The class to be used for menus under a main menu.
    """
    def __init__(self, parentmenu, name, helpshort=None, helpfull=None,
                 prompt=INHERIT):
        super().__init__(parentmenu, name, helpshort, helpfull, prompt)


class Help(_Command):
    """
    A command that shows a help screen.
    """
    def __init__(self, parentmenu, name, helpshort=None,
                 helpfull="Show this help screen"):
        super().__init__(parentmenu, name, helpshort, helpfull)

    def execute(self, *args):
        self.parentmenu.help(*args)


class Alias(_Command):
    """
    A command that executes a series of other commands.
    """
    def __init__(self, parentmenu, name, alias, helpshort=None,
                 helpfull=None):
        helpfull = helpfull or "Alias <{}>".format(alias)
        super().__init__(parentmenu, name, helpshort, helpfull)
        self.alias = SPLIT_ARGS(alias)

    def execute(self, *args):
        self.parentmenu.run_command(*self.alias, *args)


class Action(_Command):
    """
    A command that executes a function.
    """
    def __init__(self, parentmenu, name, execute, helpshort=None,
                 helpfull=None):
        helpfull = helpfull or execute
        super().__init__(parentmenu, name, helpshort, helpfull)
        self.execute = execute


class Question(_Command):
    """
    A command that prompts the user for some input text.
    """
    def __init__(self, parentmenu, name, helpshort=None, helpfull=None):
        # TODO: Implement
        raise NotImplementedError()


class Choice(_Command):
    """
    A command that prompts the user to choose from a set of answers.
    """
    def __init__(self, parentmenu, name, helpshort=None, helpfull=None):
        # TODO: Implement
        raise NotImplementedError()


class LineEditor(_Command):
    """
    A command that presents an editable string of text.
    """
    def __init__(self, parentmenu, name, load_str, save_str, helpshort=None,
                 helpfull=None):
        super().__init__(parentmenu, name, helpshort, helpfull)
        self.load_str = load_str
        self.save_str = save_str

    def execute(self, *args):
        # From http://stackoverflow.com/a/2533142/645498
        readline.set_startup_hook(lambda: readline.insert_text(self.load_str(
                                                                    *args)))
        try:
            newstr = input()
        finally:
            readline.set_startup_hook()
        self.save_str(newstr)


class TextEditor(_Command):
    """
    A command that opens text in an external editor.
    """
    def __init__(self, parentmenu, name, helpshort=None, helpfull=None):
        # TODO: Implement
        raise NotImplementedError()


class Exit(_Command):
    """
    A command that ends a command loop, usually going back to the parent menu,
    or quitting the application if run from the root menu.
    """
    def __init__(self, parentmenu, name, helpshort=None,
                 helpfull="Exit the menu"):
        super().__init__(parentmenu, name, helpshort, helpfull)

    def execute(self, *args):
        if len(args) > 0:
            print('Unrecognized arguments:', *args)
        else:
            raise self.parentmenu.EndLoops(1)


class Quit(_Command):
    """
    A command that forces quitting the application.
    """
    def __init__(self, parentmenu, name, helpshort=None,
                 helpfull="Quit the application"):
        super().__init__(parentmenu, name, helpshort, helpfull)

    def execute(self, *args):
        if len(args) > 0:
            print('Unrecognized arguments:', *args)
        else:
            sys.exit()


class CMenuError(Exception):
    pass


class DuplicatedCommandNameError(CMenuError):
    pass


class InsufficientTestCommands(CMenuError):
    pass


class InvalidPromptError(CMenuError):
    pass
