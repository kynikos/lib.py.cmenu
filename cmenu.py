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
* Additional or renamed methods, completely different implementation
* Missing methods (e.g. precmd and postcmd)
* Uses shlex.split by default
"""

READLINE_INIT = """
tab: complete
"""
INHERIT = object()


def SPLIT_ARGS(*args, **kwargs):
    try:
        return shlex.split(*args, **kwargs)
    except ValueError as exc:
        # This can happen for example if there are unclosed quotes
        raise BadCommandError(*exc.args)


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


class TestInteract:
    """
    An object that allows pausing the execution of test commands and ask for
    interactive user input.
    """
    def __init__(self, repeat=False, message=None):
        self.repeat = repeat
        self.message = message


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
            # There shouldn't be the need to protect SPLIT_ARGS from
            # BadCommandError here
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


class _CommandWithFlags(_Command):
    def __init__(self, parentmenu, name, helpshort=None, helpfull=None,
                 accepted_flags=[]):
        # TODO: Perhaps use an 'add_flag' method instead of adding accepted
        #       flags as constructor arguments
        # TODO: Automatically show list of accepted flags in 'help' message,
        #       like with menus
        super().__init__(parentmenu, name, helpshort, helpfull)
        self.accepted_flags = accepted_flags

    def complete(self, sp_args, line, rl_prefix, rl_begidx, rl_endidx):
        """
        Override in order to have command or argument completion.

        It is necessary to return a 'list', i.e. not a tuple or other
        sequences.
        """
        # TODO: Optionally check that flags are not repeated (i.e. exclude
        #       them from the possible matches if they are already in the
        #       command line)
        # TODO: Support groups of mutually-exclusive flags, i.e. if one is
        #       already present, the others in the group are not accepted
        if len(sp_args) == 0 or not line.endswith(sp_args[-1]):
            # if line.endswith(sp_args[-1]) is False, it means that the last
            # sp_args is already complete
            return self.accepted_flags
        else:
            matches = []
            for arg in self.accepted_flags:
                if arg.startswith(sp_args[-1]):
                    matches.append(arg)
            if len(matches) == 1:
                # In general, SPLIT_ARGS and readline use different word
                #  delimiters, see e.g. the docs for
                #  readline.get_completer_delims()
                # If for example there's a 'foo-bar' argument, SPLIT_ARGS sees
                #  it as a single word, but readline by default will split it
                #  in two words, 'foo' and 'bar', and if 'foo-b' is entered in
                #  the command line, and Tab is pressed, the word will be
                #  completed as 'foo-bfoo-bar', unless we compensate here by
                #  subtracting the rl_prefix from the found match
                sub = len(sp_args[-1]) - len(rl_prefix)
                return [matches[0][sub:]]
            else:
                return matches


class _Menu(_Command):
    HELP_INDENT = 2
    HELP_SPACING = 4
    BreakLoops = type('BreakLoops', (Exception, ), {})
    ResumeTests = type('ResumeTests', (Exception, ), {})

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

    # Decorator
    def _break_protected(func):
        # At one point in time there were different loop_* methods, see comment
        # on 'loop', which is why this was designed as a decorator; now this
        # could be merged into the loop method, but is instead left here in
        # case somebody wanted to create their loop methods and still easily
        # retain this functionality

        def except_(self, N):
            if self.parentmenu:
                if N is True:
                    # True ends all the loops
                    raise self.BreakLoops(True)
                elif N > 1:
                    raise self.BreakLoops(N - 1)
                else:
                    # Always reset the completer here because it depends on
                    # each (sub)menu
                    readline.set_completer(
                                        self.parentmenu.completer.complete)

        def inner(self, *args, **kwargs):
            try:
                func(self, *args, **kwargs)
            except self.BreakLoops as exc:
                except_(self, exc.args[0])
            except EOFError:
                # Raised for example when pressing Ctrl+d
                # Pressing Ctrl+d doesn't break the line apparently, so
                # explicitly print a line break
                print()
                except_(self, 1)

        return inner

    @_break_protected
    def loop(self, intro=None, cmdlines=[], test=False):
        # At one point in time there were different loop_* methods, but that
        # was giving unexpected behavior when more of them were used after each
        # other, since they were wrapped by @_break_protected one by one, and
        # when one was raising BreakLoops, the following would start, instead
        # of breaking all the loops

        # Store these values as attributes, so that they can be easily passed
        # to the submenus' loops
        # Do *not* reverse loop_cmdlines, since the value is passed between
        # submenus!
        self.loop_cmdlines = cmdlines
        self.loop_test = test

        # Always reset the completer here because it depends on each (sub)menu
        readline.set_completer(self.completer.complete)

        while True:
            try:
                cmdline = self.loop_cmdlines.pop(0)
            except IndexError:
                if self.loop_test:
                    raise InsufficientTestCommands()
                else:
                    if intro:
                        print(intro)
                        # Only print once
                        intro = None
                    cmdline = input(self.prompt)
            else:
                if isinstance(cmdline, TestInteract):
                    if cmdline.repeat:
                        # Instantiate a new TestInteract object without a
                        # message
                        self.loop_cmdlines.insert(0, TestInteract(repeat=True))
                    if cmdline.message:
                        print(cmdline.message)
                    cmdline = input(self.prompt)
                elif self.loop_test:
                    print(self.prompt, cmdline, sep='')
            try:
                self.run_line(cmdline)
            except self.ResumeTests:
                if isinstance(self.loop_cmdlines[0], TestInteract):
                    del self.loop_cmdlines[0]

    def break_loops(self, N=1):
        raise self.BreakLoops(N)

    def run_line(self, cmdline):
        if not cmdline:
            self.on_empty_line()
        else:
            try:
                cmdprefix, *args = SPLIT_ARGS(cmdline)
            except BadCommandError as exc:
                print('Bad command:', exc)
            else:
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
        #       exception, similar to the BreakLoops, that is used to prefill
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
            self.loop(cmdlines=self.parentmenu.loop_cmdlines,
                      test=self.parentmenu.loop_test)


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


class Help(_CommandWithFlags):
    """
    A command that shows a help screen.
    """
    def __init__(self, parentmenu, name, helpshort=None,
                 helpfull="Show this help screen"):
        super().__init__(parentmenu, name, helpshort, helpfull)

    def execute(self, *args):
        self.parentmenu.help(*args)


class Alias(_CommandWithFlags):
    """
    A command that executes a series of other commands.
    """
    def __init__(self, parentmenu, name, alias, helpshort=None,
                 helpfull=None):
        helpfull = helpfull or "Alias <{}>".format(alias)
        super().__init__(parentmenu, name, helpshort, helpfull)
        # Note that SPLIT_ARGS can raise BadCommandError
        self.alias = SPLIT_ARGS(alias)

    def execute(self, *args):
        self.parentmenu.run_command(*self.alias, *args)


class AliasConfig(_CommandWithFlags):
    """
    A command that manages command alias.
    """
    def __init__(self, parentmenu, name, aliasmenu, helpshort=None,
                 helpfull=None):
        super().__init__(parentmenu, name, helpshort, helpfull,
                         accepted_flags=['set', 'unset', 'unset-all'])
        self.aliasmenu = aliasmenu

    def _set(self, *args):
        try:
            command = self.aliasmenu.name_to_command[args[0]]
        except KeyError:
            pass
        else:
            if isinstance(command, Alias):
                command.uninstall()
            else:
                print('Cannot override built-in commands')
                return False
        Alias(self.aliasmenu, args[0], args[1])

    def _unset(self, *args):
        try:
            command = self.aliasmenu.name_to_command[args[0]]
        except KeyError:
            print('The alias does not exist')
        else:
            if not isinstance(command, Alias):
                print('Cannot remove built-in commands')
            else:
                command.uninstall()

    def _unset_all(self, *args):
        # list name_to_command because this loop is modifying it
        for command in list(self.aliasmenu.name_to_command.values()):
            if isinstance(command, Alias):
                command.uninstall()

    def execute(self, *args):
        try:
            args0 = args[0]
        except IndexError:
            pass
        else:
            if args0 == 'set' and len(args) == 3:
                return self._set(args[1], args[2])
            elif args0 == 'unset' and len(args) == 2:
                return self._unset(args[1])
            elif args0 == 'unset-all' and len(args) == 1:
                return self._unset_all()
        print('Wrong syntax')


class Action(_CommandWithFlags):
    """
    A command that executes a function.
    """
    def __init__(self, parentmenu, name, execute, helpshort=None,
                 helpfull=None, accepted_flags=[]):
        helpfull = helpfull or execute
        super().__init__(parentmenu, name, helpshort, helpfull,
                         accepted_flags=accepted_flags)
        self.execute = execute


class Question(_CommandWithFlags):
    """
    A command that prompts the user for some input text.
    """
    def __init__(self, parentmenu, name, helpshort=None, helpfull=None,
                 accepted_flags=[]):
        # TODO: Implement
        raise NotImplementedError()


class Choice(_CommandWithFlags):
    """
    A command that prompts the user to choose from a set of answers.
    """
    def __init__(self, parentmenu, name, helpshort=None, helpfull=None,
                 accepted_flags=[]):
        # TODO: Implement
        raise NotImplementedError()


class _LineEditor(_CommandWithFlags):
    def __init__(self, parentmenu, name, load_str, save_str, helpshort=None,
                 helpfull=None, accepted_flags=[]):
        helpfull = helpfull or load_str
        super().__init__(parentmenu, name, helpshort, helpfull,
                         accepted_flags=accepted_flags)
        self.load_str = load_str
        self.save_str = save_str

    def _edit(self, newstr=None):
        if newstr is None:
            # From http://stackoverflow.com/a/2533142/645498
            readline.set_startup_hook(lambda: readline.insert_text(
                                                            self.load_str()))
            try:
                newstr = input()
            finally:
                readline.set_startup_hook()
        self.save_str(newstr)


class LineEditor(_LineEditor):
    """
    A command that presents an editable string of text.
    """
    def __init__(self, parentmenu, name, load_str, save_str, helpshort=None,
                 helpfull=None):
        super().__init__(parentmenu, name, load_str, save_str, helpshort,
                         helpfull)

    def execute(self, *args):
        if len(args) > 1:
            print('Too many arguments')
            return False

        if len(args) == 1:
            self._edit(args[0])
        else:
            self._edit()


class LineEditorDefault(_LineEditor):
    """
    A command that presents an editable string of text or the possibility to
    restore a default value.
    """
    def __init__(self, parentmenu, name, load_str, save_str, restore_str,
                 helpshort=None, helpfull=None):
        super().__init__(parentmenu, name, load_str, save_str, helpshort,
                         helpfull, accepted_flags=['change', 'restore'])
        self.restore_str = restore_str

    def execute(self, *args):
        try:
            args0 = args[0]
        except IndexError:
            return self._edit()
        else:
            if args0 == 'change':
                if len(args) == 1:
                    return self._edit()
                elif len(args) == 2:
                    return self._edit(args[1])
            elif args0 == 'restore' and len(args) == 1:
                return self.restore_str()
        print('Wrong syntax')


class TextEditor(_CommandWithFlags):
    """
    A command that opens text in an external editor.
    """
    def __init__(self, parentmenu, name, helpshort=None, helpfull=None,
                 accepted_flags=[]):
        # TODO: Implement
        raise NotImplementedError()


class RunScript(_CommandWithFlags):
    """
    A command that runs a series of commands from a script.
    """
    def __init__(self, parentmenu, name, helpshort=None, helpfull=None):
        super().__init__(parentmenu, name, helpshort, helpfull)

    def execute(self, *args):
        if len(args) == 0:
            print('File name not specified')
        elif len(args) > 1:
            print('Too many arguments')
        else:
            try:
                script = open(args[0], 'r')
            except OSError as exc:
                print('The file cannot be opened: ' + exc.strerror)
            else:
                with script:
                    for line in script:
                        self.parentmenu.run_line(line)


class ResumeTest(_CommandWithFlags):
    """
    A command that resumes the automatic execution of test commands after being
    interrupted to ask for user input.
    """
    def __init__(self, parentmenu, name, helpshort=None,
                 helpfull="Resume testing"):
        super().__init__(parentmenu, name, helpshort, helpfull)

    def execute(self, *args):
        if len(args) > 0:
            print('Unrecognized arguments:', *args)
        else:
            raise self.parentmenu.ResumeTests()


class Exit(_CommandWithFlags):
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
            self.parentmenu.break_loops(1)


class Quit(_CommandWithFlags):
    """
    A command that breaks all the input loops, possibly causing the application
    to quit.
    """
    def __init__(self, parentmenu, name, helpshort=None,
                 helpfull="Quit the application"):
        super().__init__(parentmenu, name, helpshort, helpfull)

    def execute(self, *args):
        if len(args) > 0:
            print('Unrecognized arguments:', *args)
        else:
            self.parentmenu.break_loops(True)


class CMenuError(Exception):
    pass


class BadCommandError(CMenuError):
    pass


class DuplicatedCommandNameError(CMenuError):
    pass


class InsufficientTestCommands(CMenuError):
    pass


class InvalidPromptError(CMenuError):
    pass
