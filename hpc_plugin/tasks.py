########
# Copyright (c) 2019 EUXDAT - spiros.michalakopoulos@atos.net
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
""" Holds the plugin tasks """
import pdb
import os

import traceback
import requests
from cloudify import ctx
from cloudify.decorators import operation
from cloudify.exceptions import NonRecoverableError

from hpc_plugin.ssh import SshClient
from hpc_plugin.workload_managers.workload_manager import WorkloadManager
from hpc_plugin.external_repositories.external_repository import (
    ExternalRepository)


@operation
def preconfigure_wm(
        config,
        credentials,
        simulate,
        **kwargs):  # pylint: disable=W0613
    """ Get workload manager config from infrastructure """
    ctx.logger.info('TASKS.PY::PRECONFIGURE_WM L36')
    ctx.logger.info('Preconfiguring workload manager..')

    if not simulate:
        credentials_modified = False

        if 'ip' in ctx.target.instance.runtime_properties:
            credentials['host'] = \
                ctx.target.instance.runtime_properties['ip']
            credentials_modified = True

        for rel in ctx.target.instance.relationships:  # server relationships
            node = rel.target.node
            if node.type == 'cloudify.openstack.nodes.KeyPair':
                # take private key from openstack
                if 'private_key_path' in node.properties:
                    with open(node.properties['private_key_path'], 'r') \
                            as keyfile:
                        private_key = keyfile.read()
                        credentials['private_key'] = private_key
                        credentials_modified = True

        if credentials_modified:
            ctx.source.instance.runtime_properties['credentials'] = \
                credentials

        if 'networks' in ctx.source.instance.runtime_properties:
            ctx.source.instance.runtime_properties['networks'] = \
                ctx.target.instance.runtime_properties['networks']
        else:
            ctx.source.instance.runtime_properties['networks'] = {}
        ctx.logger.info('..preconfigured ')
    else:
        ctx.logger.warning('Workload manager simulated')

    ctx.logger.info('TASKS.PY::PRECONFIGURE_WM *** END *** L71')


@operation
def configure_execution(
        config,
        credentials,
        base_dir,
        workdir_prefix,
        simulate,
        **kwargs):  # pylint: disable=W0613
    """ Creates the working directory for the execution """
    ctx.logger.info('TASKS.PY::CONFIGURE_EXECUTION L81')
    ctx.logger.info('Connecting to workload manager..')

    if not simulate:
        wm_type = config['workload_manager']
        ctx.logger.info(' - manager: {wm_type}'.format(wm_type=wm_type))

        wm = WorkloadManager.factory(wm_type)
        if not wm:
            raise NonRecoverableError(
                "Workload Manager '" +
                wm_type +
                "' not supported.")

    	if wm_type != 'K8S':

            if 'credentials' in ctx.instance.runtime_properties:
                credentials = ctx.instance.runtime_properties['credentials']
            try:
                ctx.logger.info('TASKS.PY::CONFIGURE_EXECUTION L96')
                client = SshClient(credentials)
                ctx.logger.info('TASKS.PY::CONFIGURE_EXECUTION L98')
            except Exception as exp:
                raise NonRecoverableError(
                    "Failed trying to connect to workload manager: " + str(exp))

            ctx.logger.info('TASKS.PY::CONFIGURE_EXECUTION L103')
            # TODO: use command according to wm
            _, exit_code = client.execute_shell_command(
                'uname',
                wait_result=True)

            ctx.logger.info('TASKS.PY::CONFIGURE_EXECUTION L109')

            if exit_code is not 0:
                client.close_connection()
                raise NonRecoverableError(
                    "Failed executing on the workload manager: exit code " +
                    str(exit_code))

            ctx.instance.runtime_properties['login'] = exit_code is 0

        prefix = workdir_prefix
        if workdir_prefix is "":
            prefix = ctx.blueprint.id

        if wm_type != 'K8S':
            workdir = wm.create_new_workdir(client, base_dir, prefix, ctx.logger)
            client.close_connection()
        else:
            workdir = wm.k8s_create_new_workdir(base_dir, prefix, ctx.logger)

        if workdir is None:
            raise NonRecoverableError(
                "failed to create the working directory, base dir: " +
                base_dir)
        ctx.instance.runtime_properties['workdir'] = workdir
        ctx.logger.info('..workload manager ready to be used on ' + workdir)
    else:
        ctx.logger.info(' - [simulation]..')
        ctx.instance.runtime_properties['login'] = True
        ctx.instance.runtime_properties['workdir'] = "simulation"
        ctx.logger.warning('Workload manager connection simulated')

    ctx.logger.info('TASKS.PY::CONFIGURE_EXECUTION *** END *** L141')


@operation
def cleanup_execution(
        config,
        credentials,
        skip,
        simulate,
        **kwargs):  # pylint: disable=W0613
    """ Cleans execution working directory """
    ctx.logger.info('TASKS.PY::CLEANUP_EXECUTION L148')
    if skip:
        ctx.logger.info('TASKS.PY::CLEANUP_EXECUTION *** SKIP *** L154')
        return

    ctx.logger.info('Cleaning up...')
    if not simulate:
        workdir = ctx.instance.runtime_properties['workdir']
        wm_type = config['workload_manager']
        wm = WorkloadManager.factory(wm_type)
        if not wm:
            raise NonRecoverableError(
                "Workload Manager '" +
                wm_type +
                "' not supported.")

        if 'credentials' in ctx.instance.runtime_properties:
            credentials = ctx.instance.runtime_properties['credentials']

        if wm_type != 'K8S':
            client = SshClient(credentials)
            client.execute_shell_command(
                'rm -r ' + workdir,
                wait_result=True)
            client.close_connection()
        else:
            try:
                os.rmdir(workdir)
            except Exception as exp:
                print(traceback.format_exc())
                ctx.logger.error(
                    'Something happend when trying to clean up: ' + 
                    exp.message)

        ctx.logger.info('..all clean.')
    else:
        ctx.logger.warning('clean up simulated.')

    ctx.logger.info('TASKS.PY::CLEANUP_EXECUTION *** END *** L179')


@operation
def start_monitoring_hpc(
        config,
        credentials,
        external_monitor_entrypoint,
        external_monitor_port,
        external_monitor_orchestrator_port,
        simulate,
        **kwargs):  # pylint: disable=W0613
    """ Starts monitoring using the Monitor orchestrator """
    ctx.logger.info('TASKS.PY::START_MONITORING_HPC L185')
    external_monitor_entrypoint = None  # FIXME: external monitor disabled
    if external_monitor_entrypoint:
        ctx.logger.info('Starting infrastructure monitor..')

        if not simulate:
            if 'credentials' in ctx.instance.runtime_properties:
                credentials = ctx.instance.runtime_properties['credentials']
            workload_manager = config['workload_manager']
            country_tz = config['country_tz']

            url = 'http://' + external_monitor_entrypoint + \
                external_monitor_orchestrator_port + '/exporters/add'

            # FIXME: credentials doesn't have to have a password anymore
            payload = ("{\n\t\"host\": \"" + credentials['host'] +
                       "\",\n\t\"type\": \"" + workload_manager +
                       "\",\n\t\"persistent\": false,\n\t\"args\": {\n\t\t\""
                       "user\": \"" + credentials['user'] + "\",\n\t\t\""
                       "pass\": \"" + credentials['password'] + "\",\n\t\t\""
                       "tz\": \"" + country_tz + "\",\n\t\t\""
                       "log\": \"debug\"\n\t}\n}")
            headers = {
                'content-type': "application/json",
                'cache-control': "no-cache",
            }

            ctx.logger.info('TASKS.PY::START_MONITORING_HPC() L208')
            response = requests.request(
                "POST", url, data=payload, headers=headers)

            if response.status_code != 201:
                raise NonRecoverableError(
                    "failed to start node monitor: " + str(response
                                                           .status_code))
        else:
            ctx.logger.warning('monitor simulated')

    ctx.logger.info('TASKS.PY::START_MONITORING_HPC *** END *** L230')


@operation
def stop_monitoring_hpc(
        config,
        credentials,
        external_monitor_entrypoint,
        external_monitor_port,
        external_monitor_orchestrator_port,
        simulate,
        **kwargs):  # pylint: disable=W0613
    """ Stops monitoring using the Monitor Orchestrator """
    ctx.logger.info('TASKS.PY::START_MONITORING_HPC L234')
    external_monitor_entrypoint = None  # FIXME: external monitor disabled
    if external_monitor_entrypoint:
        ctx.logger.info('Stoping infrastructure monitor..')

        if not simulate:
            if 'credentials' in ctx.instance.runtime_properties:
                credentials = ctx.instance.runtime_properties['credentials']
            workload_manager = config['workload_manager']
            country_tz = config['country_tz']

            url = 'http://' + external_monitor_entrypoint + \
                external_monitor_orchestrator_port + '/exporters/remove'

            # FIXME: credentials doesn't have to have a password anymore
            payload = ("{\n\t\"host\": \"" + credentials['host'] +
                       "\",\n\t\"type\": \"" + workload_manager +
                       "\",\n\t\"persistent\": false,\n\t\"args\": {\n\t\t\""
                       "user\": \"" + credentials['user'] + "\",\n\t\t\""
                       "pass\": \"" + credentials['password'] + "\",\n\t\t\""
                       "tz\": \"" + country_tz + "\",\n\t\t\""
                       "log\": \"debug\"\n\t}\n}")
            headers = {
                'content-type': "application/json",
                'cache-control': "no-cache",
            }

            response = requests.request(
                "POST", url, data=payload, headers=headers)

            if response.status_code != 200:
                if response.status_code == 409:
                    ctx.logger.warning(
                        'Already removed on the exporter orchestrator.')
                else:
                    raise NonRecoverableError(
                        "failed to stop node monitor: " + str(response
                                                              .status_code))
        else:
            ctx.logger.warning('monitor simulated')

    ctx.logger.info('TASKS.PY::START_MONITORING_HPC *** END *** L284')


@operation
def preconfigure_job(
        config,
        credentials,
        external_monitor_entrypoint,
        external_monitor_port,
        external_monitor_type,
        external_monitor_orchestrator_port,
        job_prefix,
        monitor_period,
        simulate,
        **kwargs):  # pylint: disable=W0613
    """ Match the job with its credentials """
    ctx.logger.info('TASKS.PY::PRECONFIGURE_JOB L289')
    ctx.logger.info('Preconfiguring job..')

    if 'credentials' not in ctx.target.instance.runtime_properties:
        ctx.source.instance.runtime_properties['credentials'] = \
            credentials
    else:
        ctx.source.instance.runtime_properties['credentials'] = \
            ctx.target.instance.runtime_properties['credentials']

    ctx.source.instance.runtime_properties['external_monitor_entrypoint'] = \
        external_monitor_entrypoint
    ctx.source.instance.runtime_properties['external_monitor_port'] = \
        external_monitor_port
    ctx.source.instance.runtime_properties['external_monitor_type'] = \
        external_monitor_type
    ctx.source.instance.runtime_properties['monitor_orchestrator_port'] = \
        external_monitor_orchestrator_port
    ctx.source.instance.runtime_properties['workload_manager'] = \
        config['workload_manager']
    ctx.source.instance.runtime_properties['simulate'] = simulate
    ctx.source.instance.runtime_properties['job_prefix'] = job_prefix
    ctx.source.instance.runtime_properties['monitor_period'] = monitor_period

    ctx.source.instance.runtime_properties['workdir'] = \
        ctx.target.instance.runtime_properties['workdir']

    ctx.logger.info('TASKS.PY::PRECONFIGURE_JOB *** END *** L327')

@operation
def bootstrap_job(
        deployment,
        skip_cleanup,
        **kwarsgs):  # pylint: disable=W0613
    """Bootstrap a job with a script that receives SSH credentials as imput"""
    ctx.logger.info('TASKS.PY::BOOTSTRAP_JOB L323')
    if not deployment:
        return

    ctx.logger.info('Bootstrapping job..')
    simulate = ctx.instance.runtime_properties['simulate']

    if not simulate and 'bootstrap' in deployment:
        inputs = deployment['inputs'] if 'inputs' in deployment else []
        credentials = ctx.instance.runtime_properties['credentials']
        workdir = ctx.instance.runtime_properties['workdir']
        name = "bootstrap_" + ctx.instance.id + ".sh"
        wm_type = ctx.instance.runtime_properties['workload_manager']

        if deploy_job(
                deployment['bootstrap'],
                inputs,
                credentials,
                wm_type,
                workdir,
                name,
                ctx.logger,
                skip_cleanup):
            ctx.logger.info('..job bootstrapped')
        else:
            ctx.logger.error('Job not bootstrapped')
            raise NonRecoverableError("Bootstrap failed")
    else:
        if 'bootstrap' in deployment:
            ctx.logger.warning('..bootstrap simulated')
        else:
            ctx.logger.info('..nothing to bootstrap')

    ctx.logger.info('TASKS.PY::BOOTSTRAP_JOB L368')


@operation
def revert_job(deployment, skip_cleanup, **kwarsgs):  # pylint: disable=W0613
    """Revert a job using a script that receives SSH credentials as input"""
    ctx.logger.info('TASKS.PY::REVERT_JOB L360')
    if not deployment:
        ctx.logger.info('TASKS.PY::REVERT_JOB *** SKIP *** L376')
        return

    ctx.logger.info('Reverting job..')
    try:
        simulate = ctx.instance.runtime_properties['simulate']

        if not simulate and 'revert' in deployment:
            inputs = deployment['inputs'] if 'inputs' in deployment else []
            credentials = ctx.instance.runtime_properties['credentials']
            workdir = ctx.instance.runtime_properties['workdir']
            name = "revert_" + ctx.instance.id + ".sh"
            wm_type = ctx.instance.runtime_properties['workload_manager']

            if deploy_job(
                    deployment['revert'],
                    inputs,
                    credentials,
                    wm_type,
                    workdir,
                    name,
                    ctx.logger,
                    skip_cleanup):
                ctx.logger.info('..job reverted')
            else:
                ctx.logger.error('Job not reverted')
                raise NonRecoverableError("Revert failed")
        else:
            if 'revert' in deployment:
                ctx.logger.warning('..revert simulated')
            else:
                ctx.logger.info('..nothing to revert')
    except KeyError:
        # The job wasn't configured properly, so there was no bootstrap
        ctx.logger.warning('Job was not reverted as it was not configured')

    ctx.logger.info('TASKS.PY::REVERT_JOB *** END *** L412')


def deploy_job(script,
               inputs,
               credentials,
               wm_type,
               workdir,
               name,
               logger,
               skip_cleanup):  # pylint: disable=W0613
    """ Exec a deployment job script that receives SSH credentials as input """

    wm = WorkloadManager.factory(wm_type)
    if not wm:
        raise NonRecoverableError(
            "Workload Manager '" +
            wm_type +
            "' not supported.")

    # Execute the script and manage the output
    success = False
    client = SshClient(credentials)
    if wm._create_shell_script(client,
                               name,
                               ctx.get_resource(script),
                               logger,
                               workdir=workdir):
        call = "./" + name
        for dinput in inputs:
            str_input = str(dinput)
            if ('\n' in str_input or ' ' in str_input) and str_input[0] != '"':
                call += ' "' + str_input + '"'
            else:
                call += ' ' + str_input
        _, exit_code = client.execute_shell_command(
            call,
            workdir=workdir,
            wait_result=True)
        if exit_code is not 0:
            logger.warning(
                "failed to deploy job: call '" + call + "', exit code " +
                str(exit_code))
        else:
            success = True

        if not skip_cleanup:
            if not client.execute_shell_command(
                    "rm " + name,
                    workdir=workdir):
                logger.warning("failed removing bootstrap script")

    client.close_connection()

    return success


@operation
def send_job(job_options, **kwargs):  # pylint: disable=W0613
    """ Sends a job to the workload manager """
    ctx.logger.info('TASKS.PY::SEND_JOB L455')
    simulate = ctx.instance.runtime_properties['simulate']

    name = kwargs['name']
    is_singularity = 'hpc.nodes.SingularityJob' in ctx.node.\
        type_hierarchy

    if not simulate:
        workdir = ctx.instance.runtime_properties['workdir']
        wm_type = ctx.instance.runtime_properties['workload_manager']
        client = SshClient(ctx.instance.runtime_properties['credentials'])

        wm = WorkloadManager.factory(wm_type)
        if not wm:
            client.close_connection()
            raise NonRecoverableError(
                "Workload Manager '" +
                wm_type +
                "' not supported.")
        context_vars = {
            'CFY_EXECUTION_ID': ctx.execution_id,
            'CFY_JOB_NAME': name
        }
        is_submitted = wm.submit_job(client,
                                     name,
                                     job_options,
                                     is_singularity,
                                     ctx.logger,
                                     workdir=workdir,
                                     context=context_vars)
        client.close_connection()
    else:
        ctx.logger.warning('Instance ' + ctx.instance.id + ' simulated')
        is_submitted = True

    if is_submitted:
        ctx.logger.info('Job ' + name + ' (' + ctx.instance.id + ') sent.')
    else:
        ctx.logger.error(
            'Job ' + name + ' (' + ctx.instance.id + ') not sent.')
        raise NonRecoverableError(
            'Job ' + name + ' (' + ctx.instance.id + ') not sent.')

    ctx.instance.runtime_properties['job_name'] = name

    ctx.logger.info('TASKS.PY::SEND_JOB *** END *** L517')


@operation
def cleanup_job(job_options, skip, **kwargs):  # pylint: disable=W0613
    ctx.logger.info('TASKS.PY::PRECONFIGURE_WM L503')
    """Clean the aux files of the job"""
    if skip:
        return

    try:
        simulate = ctx.instance.runtime_properties['simulate']
    except KeyError:
        # The job wasn't configured properly, so no cleanup needed
        ctx.logger.warning('Job was not cleaned up as it was not configured.')

    try:
        name = kwargs['name']
        if not simulate:
            is_singularity = 'hpc.nodes.SingularityJob' in ctx.node.\
                type_hierarchy
            workdir = ctx.instance.runtime_properties['workdir']
            wm_type = ctx.instance.runtime_properties['workload_manager']

            client = SshClient(ctx.instance.runtime_properties['credentials'])

            wm = WorkloadManager.factory(wm_type)
            if not wm:
                client.close_connection()
                raise NonRecoverableError(
                    "Workload Manager '" +
                    wm_type +
                    "' not supported.")
            is_clean = wm.clean_job_aux_files(client,
                                              name,
                                              job_options,
                                              is_singularity,
                                              ctx.logger,
                                              workdir=workdir)

            client.close_connection()
        else:
            ctx.logger.warning('Instance ' + ctx.instance.id + ' simulated')
            is_clean = True

        if is_clean:
            ctx.logger.info(
                'Job ' + name + ' (' + ctx.instance.id + ') cleaned.')
        else:
            ctx.logger.error('Job ' + name + ' (' + ctx.instance.id +
                             ') not cleaned.')
    except Exception as exp:
        print(traceback.format_exc())
        ctx.logger.error(
            'Something happend when trying to clean up: ' + exp.message)

    ctx.logger.info('TASKS.PY::PRECONFIGURE_WM L573')


@operation
def stop_job(job_options, **kwargs):  # pylint: disable=W0613
    ctx.logger.info('TASKS.PY::STOP_JOB L557')
    """ Stops a job in the workload manager """
    try:
        simulate = ctx.instance.runtime_properties['simulate']
    except KeyError:
        # The job wasn't configured properly, no need to be stopped
        ctx.logger.warning('Job was not stopped as it was not configured.')

    try:
        name = kwargs['name']
        is_singularity = 'hpc.nodes.SingularityJob' in ctx.node.\
            type_hierarchy

        if not simulate:
            workdir = ctx.instance.runtime_properties['workdir']
            wm_type = ctx.instance.runtime_properties['workload_manager']
            client = SshClient(ctx.instance.runtime_properties['credentials'])

            wm = WorkloadManager.factory(wm_type)
            if not wm:
                client.close_connection()
                raise NonRecoverableError(
                    "Workload Manager '" +
                    wm_type +
                    "' not supported.")
            is_stopped = wm.stop_job(client,
                                     name,
                                     job_options,
                                     is_singularity,
                                     ctx.logger,
                                     workdir=workdir)

            client.close_connection()
        else:
            ctx.logger.warning('Instance ' + ctx.instance.id + ' simulated')
            is_stopped = True

        if is_stopped:
            ctx.logger.info(
                'Job ' + name + ' (' + ctx.instance.id + ') stopped.')
        else:
            ctx.logger.error('Job ' + name + ' (' + ctx.instance.id +
                             ') not stopped.')
            raise NonRecoverableError('Job ' + name + ' (' + ctx.instance.id +
                                      ') not stopped.')
    except Exception as exp:
        print(traceback.format_exc())
        ctx.logger.error(
            'Something happend when trying to stop: ' + exp.message)

    ctx.logger.info('TASKS.PY::STOP_JOB L628')


@operation
def publish(publish_list, **kwargs):
    ctx.logger.info('TASKS.PY::PRECONFIGURE_WM L610')
    """ Publish the job outputs """
    try:
        simulate = ctx.instance.runtime_properties['simulate']
    except KeyError as exp:
        # The job wasn't configured properly, no need to publish
        ctx.logger.warning(
            'Job outputs where not published as' +
            ' the job was not configured properly.')
        return

    try:
        name = kwargs['name']
        published = True
        if not simulate:
            workdir = ctx.instance.runtime_properties['workdir']
            client = SshClient(ctx.instance.runtime_properties['credentials'])

            for publish_item in publish_list:
                if not published:
                    break
                exrep = ExternalRepository.factory(publish_item)
                if not exrep:
                    client.close_connection()
                    raise NonRecoverableError(
                        "External repository '" +
                        publish_item['dataset']['type'] +
                        "' not supported.")
                published = exrep.publish(client, ctx.logger, workdir)

            client.close_connection()
        else:
            ctx.logger.warning('Instance ' + ctx.instance.id + ' simulated')

        if published:
            ctx.logger.info(
                'Job ' + name + ' (' + ctx.instance.id + ') published.')
        else:
            ctx.logger.error('Job ' + name + ' (' + ctx.instance.id +
                             ') not published.')
            raise NonRecoverableError('Job ' + name + ' (' + ctx.instance.id +
                                      ') not published.')
    except Exception as exp:
        print(traceback.format_exc())
        ctx.logger.error(
            'Cannot publish: ' + exp.message)

    ctx.logger.info('TASKS.PY::PRECONFIGURE_WM L680')
