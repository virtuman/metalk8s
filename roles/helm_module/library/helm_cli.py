import os
import json

from contextlib import contextmanager
from tempfile import NamedTemporaryFile

from ansible.module_utils.basic import *  # noqa


class Helm(AnsibleModule):

    def __init__(self, *args, **kwargs):
        AnsibleModule.__init__(
            self,
            argument_spec=dict(
                chart=dict(type='dict'),
                release=dict(type='str', aliases=['name']),
                namespace=dict(type='str'),
                binary=dict(type='str'),
                state=dict(default='present', choice=['present', 'absent']),
                values_list=dict(type='list'),
            )
        )
        self._helm_bin = None
        self.delete_temp_file = True

    def get_chart(self):
        chart = self.params.get('chart')
        if chart is None:
            raise HelmError("'chart' is a mandatory argument for state=present")
        if 'name' not in chart:
            raise HelmError("'chart' argument required a 'name' key for state=present")
        return chart

    @property
    def helm_bin(self):
        if self._helm_bin is None:
            binary = self.params.get('binary')
            if binary and os.path.isfile(binary):
                self._helm_bin = binary
            else:
                self._helm_bin = self.get_bin_path(
                    'helm',
                    required=True,
                    opt_dirs=[binary] if binary else None)
        return self._helm_bin

    def get_release_info(self, release):
        def failure_detect(rc, out, err):
            return not(rc == 0 or
                       'release: "{}" not found'.format(release) in err)

        rc, out, err = self._run_helm(['get', release],
                                      failed_when=failure_detect)
        if rc != 0:
            return
        release_info = self._parse_helm_output(out)
        return release_info

    def install(self):
        chart = self.get_chart()
        release = self.params.get('release')
        if release is None:
            cmd = ['install', chart['name']]
        else:
            cmd = ['--install', release, 'upgrade', chart['name']]
        if 'version' in chart:
            cmd.extend(['--version', chart['version']])
        if 'repo' in chart:
            cmd.extend(['--repo', chart['repo']])
        namespace = self.params.get('namespace')
        if namespace:
            cmd.extend(['--namespace', namespace])
        with self.write_values_files() as values_filenames:
            for value in values_filenames:
                cmd.extend(['--values', value])
            rc, out, err = self._run_helm(cmd)
        return self._parse_helm_output(out)

    def _run_helm(self, cmd, failed_when=None):
        if failed_when is None:
            failed_when = self._helm_std_failure
        try:
            rc, out, err = self.run_command([self.helm_bin] + cmd)
        except Exception as exc:
            raise HelmError('error running helm {} command: {}'.format(
                ' '.join(cmd), exc))
        else:
            if failed_when(rc, out, err):
                raise HelmError('Error running helm {} command (rc={}) '
                                "out='{}' err='{}'".format(' '.join(cmd), rc, out, err))
        return rc, out, err

    @staticmethod
    def _helm_std_failure(rc, out, err):
        return rc != 0

    def check_present(self):
        release = self.params.get('release')
        if release:
            release_info_pre = self.get_release_info(release)
        else:
            release_info_pre = None

        install = self.install()
        release_info_post = self.get_release_info(release or install['NAME'])
        return {'changed': release_info_pre != release_info_post,
                'release_info_pre': release_info_pre,
                'install': install,
                'release_info_post': release_info_post}

    def execute(self):
        state = self.params.get('state')
        if state == 'present':
            return self.check_present()

    @contextmanager
    def write_values_files(self):
        values_filenames = []
        values_content = self.params.get('values_list', [])
        for values in values_content:
            temp = NamedTemporaryFile(
                suffix='.yaml',
                prefix='ansible.helm.values.',
                delete=False,
            )
            if isinstance(values, dict):
                values_str = json.dumps(values)
            else:
                values_str = values
            temp.write(values_str)
            temp.close()
            values_filenames.append(temp.name)
        try:
            yield values_filenames
        finally:
            if self.delete_temp_file:
                for filename in values_filenames:
                    os.remove(filename)

    def _parse_helm_output(self, helm_output):
        output_parsed = {}
        multiline_key = None
        for n, line in enumerate(helm_output.splitlines()):
            line_split = line.split(':', 1)
            try:
                (key, value) = line_split
            except ValueError:
                pass
            else:
                if key.strip().upper() == key:
                    if value.strip() == '':
                        multiline_key = key
                        output_parsed[key] = []
                        continue
                    else:
                        output_parsed[key] = value.strip()
                        multiline_key = None
                        continue
            if multiline_key is not None:
                output_parsed[multiline_key].append(line)
                continue
            if n == 0:
                output_parsed['message'] = line
                continue
            if line == '':
                continue
            raise ValueError(
                'Cannot have an unformatted line in a '
                'non-multine block: "{}" (n {})'.format(line, n)
            )
        return output_parsed


class HelmError(Exception):
    """Error from Kubectl Module"""


def main():
    module = Helm()
    try:
        res_dict = module.execute()
    except HelmError as exc:
        module.fail_json(msg=exc.args[0])
    else:
        module.exit_json(**res_dict)


if __name__ == '__main__':
    main()
