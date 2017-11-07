import os
from buildstream import utils
from buildstream import Element, ElementError


class FakeIntegrationElement(Element):
    def configure(self, node):
        pass

    def preflight(self):
        pass

    def get_unique_key(self):
        pass

    def configure_sandbox(self, sandbox):
        pass

    def stage(self, sandbox):
        pass

    def assemble(self, sandbox):
        return '/'

    def integrate(self, sandbox):
        directory = sandbox.get_directory()
        bstdata = self.get_public_data('bst')

        if bstdata is not None:
            commands = self.node_get_member(bstdata, list, 'integration-commands', default_value=[])
            for i in range(len(commands)):
                cmd = self.node_subst_list_element(bstdata, 'integration-commands', [i])
                args = cmd.split(':')
                f = os.path.join(directory, args[1])
                if args[0] == "touch":
                    os.unlink(f)
                    with open(f, 'w') as fd:
                        fd.write("content\n")
                elif args[0] == "delete":
                    os.unlink(f)
                elif args[0] == "add":
                    with open(f, 'w') as fd:
                        fd.write("content\n")
                elif args[0] == "link":
                    os.symlink(args[2], f)
                elif args[0] == "mkdir":
                    os.mkdir(f)
                elif args[0] == "rmdir":
                    os.rmdir(f)
                else:
                    raise ElementError("Unexpected command: {}".format(args[0]))


def setup():
    return FakeIntegrationElement
