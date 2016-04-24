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

import shlex as _m_shlex
import readline as _m_readline
from collections import OrderedDict

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

SPLITARGS = _m_shlex.split


class DynamicPrompt:
    """
    A _Menu prompt that automatically shows the path of submenus.
    """
    def __init__(self, prefix='(', separator='>', suffix=') '):
        self.prefix = prefix
        self.separator = separator
        self.suffix = suffix

    def associate(self, menu):
        self.menu = menu
        path = [self.menu.name]
        parentmenu = self.menu.parentmenu
        while parentmenu:
            path.append(parentmenu.name)
            parentmenu = parentmenu.parentmenu
        self.prompt = ''.join((self.prefix,
                               self.separator.join(reversed(path)),
                               self.suffix))

    @classmethod
    def inherit(cls, menu):
        pprompt = menu.parentmenu.prompt
        self = cls(prefix=pprompt.prefix,
                   separator=pprompt.separator,
                   suffix=pprompt.suffix)
        self.associate(menu)
        return self

    def __str__(self):
        return self.prompt


class _Command:
    def __init__(self, parentmenu, name, helpfull, helpshort=None):
        self.parentmenu = parentmenu
        self.name = name
        self.helpfull = helpfull
        # TODO: Initial empty lines should be discarded
        self.helpshort = helpshort or helpfull.split('\n', 1)[0]

        if parentmenu:
            parentmenu.add_command(self)

    def help(self, *args):
        """
        Can be overridden (and for example _Menu does).
        """
        if args:
            print('Invalid arguments:', *args)
        else:
            print(self.helpfull)
        return False

    def set_completer(self):
        """
        Can be overridden.
        """
        # TODO: Set a default
        pass

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

        if isinstance(prompt, DynamicPrompt):
            self.prompt = prompt
            prompt.associate(self)
        elif prompt is self.INHERIT:
            if parentmenu:
                if isinstance(parentmenu.prompt, DynamicPrompt):
                    self.prompt = DynamicPrompt.inherit(self)
                else:
                    self.prompt = parentmenu.prompt
            else:
                raise InvalidPromptError()
        else:
            self.prompt = prompt

        self.name_to_command = OrderedDict()

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
        cmdprefix, *args = SPLITARGS(cmdline)
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
        print(*self.name_to_command.keys())
        return False

    def on_bad_command(self, cmdprefix, *args):
        print('Unrecognized command:', cmdprefix)
        return False

    def on_ambiguous_command(self, cmdmatches, cmdprefix, *args):
        print('Ambiguous command:', cmdprefix,
              '[' + ','.join(cmd.name for cmd in cmdmatches) + ']')
        return False

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

    def set_completer(self):
        # TODO: Implement
        print()
        print('text', text)
        print('line', line)
        print('begidx', begidx)
        print('endidx', endidx)
        return [attr[3:] for attr in dir(self.configmenu) if attr[:3] == 'do_']

    def execute(self, *args):
        if args:
            return self.run_line(args)
        else:
            return self.loop_input()


class RootMenu(_Menu):
    """
    The class to be used for the main menu of an application.
    """
    def __init__(self, name, helpheader, prompt=None):
        super().__init__(None, name, helpheader, prompt or DynamicPrompt())


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
        self.alias = SPLITARGS(alias)

    def execute(self, *args):
        return self.parentmenu.run_command(*self.alias, *args)


class Action(_Command):
    """
    A command that executes a function.
    """
    def execute(self, *args):
        # TODO: Implement
        raise NotImplementedError()


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
