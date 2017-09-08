#!/usr/bin/env python
# Copyright (c) 2017 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Script that uploads the specified Skia Gerrit change to Android.

This script does the following:
* Downloads the repo tool.
* Inits and checks out the bare-minimum required Android checkout.
* Sets the required git config options in external/skia.
* Cherry-picks the specified Skia patch.
* Modifies the change subject to append a "Test:" line required for presubmits.
* Uploads the Skia change to Android's Gerrit instance.

After the change is uploaded to Android, developers can trigger TH and download
binaries (if required) after runs complete.

The script re-uses the workdir when it is run again. To start from a clean slate
delete the workdir.

Timings:
* ~1m15s when using an empty/non-existent workdir for the first time.
* ~15s when using a workdir previously populated by the script.

Example usage:
  $ python upload_to_android.py -w /repos/testing -c 44200
"""

import argparse
import json
import os
import subprocess
import stat
import urllib2


REPO_TOOL_URL = 'https://storage.googleapis.com/git-repo-downloads/repo'
SKIA_PATH_IN_ANDROID = os.path.join('external', 'skia')
ANDROID_REPO_URL = 'https://googleplex-android.googlesource.com'
REPO_BRANCH_NAME = 'experiment'
SKIA_GERRIT_INSTANCE = 'https://skia-review.googlesource.com'


def get_change_details(change_num):
  response = urllib2.urlopen('%s/changes/%s/detail?o=ALL_REVISIONS' % (
                                 SKIA_GERRIT_INSTANCE, change_num), timeout=5)
  content = response.read()
  # Remove the first line which contains ")]}'\n".
  return json.loads(content[5:])


def upload_to_android(work_dir, change_num):
  if not os.path.isdir(work_dir):
    print 'Creating %s' % work_dir
    os.makedirs(work_dir)

  # Ensure the repo tool exists in the work_dir.
  repo_dir = os.path.join(work_dir, 'bin')
  repo_binary = os.path.join(repo_dir, 'repo')
  if not os.path.isdir(repo_dir):
    print 'Creating %s' % repo_dir
    os.makedirs(repo_dir)
  if not os.path.exists(repo_binary):
    print 'Downloading %s from %s' % (repo_binary, REPO_TOOL_URL)
    response = urllib2.urlopen(REPO_TOOL_URL, timeout=5)
    content = response.read()
    with open(repo_binary, 'w') as f:
      f.write(content)
    # Set executable bit.
    st = os.stat(repo_binary)
    os.chmod(repo_binary, st.st_mode | stat.S_IEXEC)

  # Create android-repo directory in the work_dir.
  android_dir = os.path.join(work_dir, 'android-repo')
  if not os.path.isdir(android_dir):
    print 'Creating %s' % android_dir
    os.makedirs(android_dir)

  print """

About to run repo init. If it hangs asking you to run glogin then please:
* Exit the script (ctrl-c).
* Run 'glogin'.
* Re-run the script.

"""
  os.chdir(android_dir)
  subprocess.check_call(
      '%s init -u %s/a/platform/manifest -g "all,-notdefault,-darwin" -b master'
          % (repo_binary, ANDROID_REPO_URL), shell=True)

  print 'Syncing the Android checkout at %s' % android_dir
  print '%s sync %s tools/repohooks -j 32' % (
                            repo_binary, SKIA_PATH_IN_ANDROID)
  subprocess.check_call('%s sync %s tools/repohooks -j 32' % (
                            repo_binary, SKIA_PATH_IN_ANDROID), shell=True)

  # Set the necessary git config options.
  os.chdir(SKIA_PATH_IN_ANDROID)
  subprocess.check_call(
      'git config remote.goog.review %s/' % ANDROID_REPO_URL, shell=True)
  subprocess.check_call(
      'git config review.%s/.autoupload true' % ANDROID_REPO_URL, shell=True)

  # Create repo branch.
  subprocess.check_call('%s start %s .' % (repo_binary, REPO_BRANCH_NAME),
                        shell=True)
  try:
    change_details = get_change_details(change_num)

    # Download and cherry-pick the patch.
    latest_patchset = len(change_details['revisions'])
    mod = int(change_num) % 100
    download_ref = 'refs/changes/%s/%s/%s' % (
                       str(mod).zfill(2), change_num, latest_patchset)
    subprocess.check_call(
        'git fetch https://skia.googlesource.com/skia %s' % download_ref,
        shell=True)
    subprocess.check_call('git cherry-pick FETCH_HEAD', shell=True)

    # Amend the commit message to add "Test:" which is required by Android
    # presubmit checks.
    original_commit_message = change_details['subject']
    new_commit_message = (
        "%s\n\nTest: Presubmit checks will test this change." % (
            original_commit_message))
    subprocess.check_call('git commit --amend -m "%s"' % new_commit_message,
                          shell=True)

    # Upload to Android Gerrit.
    subprocess.check_call('%s upload --verify' % repo_binary, shell=True)

    print """

Open the above URL and trigger TH by checking 'Presubmit-Ready'.
You can download binaries (if required) from the TH link after it completes.
"""
  finally:
    # Abandon repo branch.
    subprocess.call('%s abandon %s' % (repo_binary, REPO_BRANCH_NAME),
                    shell=True)


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument(
      '--work-dir', '-w', required=True,
      help='Directory where an Android checkout will be created (if it does '
           'not already exist). Note: ~1GB space will be used.')
  parser.add_argument(
      '--change-num', '-c', required=True,
      help='The skia-rev Gerrit change number that should be patched into '
           'Android.')
  args = parser.parse_args()
  upload_to_android(args.work_dir, args.change_num)


if __name__ == '__main__':
  main()
