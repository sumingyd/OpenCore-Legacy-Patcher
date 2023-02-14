#!/usr/bin/env python3

# Generate stand alone application for OpenCore-Patcher
# Copyright (C) 2022-2023 - Mykola Grymalyuk

from pathlib import Path
import time
import argparse
import os
import subprocess
import plistlib
import time
import sys

from resources import constants


class CreateBinary:
    """
    Library for creating OpenCore-Patcher application

    This script's main purpose is to handle the following:
       - Download external dependancies (ex. PatcherSupportPkg)
       - Convert payloads directory into DMG
       - Build Binary via Pyinstaller
       - Patch 'LC_VERSION_MIN_MACOSX' to OS X 10.10
       - Add commit data to Info.plist

    """

    def __init__(self):
        start = time.time()
        print("- Starting build script")

        self.args = self._parse_arguments()

        self._set_cwd()

        self._preflight_processes()
        self._build_binary()
        self._postflight_processes()
        print(f"- Build script completed in {str(round(time.time() - start, 2))} seconds")


    def _set_cwd(self):
        """
        Initialize current working directory to parent of this script
        """

        os.chdir(Path(__file__).resolve().parent)
        print(f"- Current Working Directory: \n\t{os.getcwd()}")


    def _parse_arguments(self):
        """
        Parse arguments passed to script
        """

        parser = argparse.ArgumentParser(description='Builds OpenCore-Patcher binary')
        parser.add_argument('--branch', type=str, help='Git branch name')
        parser.add_argument('--commit', type=str, help='Git commit URL')
        parser.add_argument('--commit_date', type=str, help='Git commit date')
        parser.add_argument('--reset_binaries', action='store_true', help='Force redownload and imaging of payloads')
        args = parser.parse_args()
        return args


    def _setup_pathing(self):
        """
        Initialize pathing for pyinstaller
        """

        python_path = sys.executable
        python_binary = python_path.split("/")[-1]
        python_bin_dir = python_path.strip(python_binary)

        # macOS (using Python installed by homebrew (e.g. brew))
        if f"/usr/local/opt/python@3." in sys.executable:
            print(f"\t* NOTE: home(brew) python3 detected; using (sys.exec_prefix, python_path) ==> {sys.exec_prefix, python_path}")
            # - under brew, pip3 will install pyinstaller at:
            #   /usr/local/lib/python3.9/site-packages/pyinstaller
            #   and /usr/local/bin/pyinstaller stub to load and run.

            pyinstaller_path = f"/usr/local/bin/pyinstaller"
        else:
            pyinstaller_path = f"{python_bin_dir}pyinstaller"

        if not Path(pyinstaller_path).exists():
            print(f"  - pyinstaller not found:\n\t{pyinstaller_path}")
            raise Exception("pyinstaller not found")

        self.pyinstaller_path = pyinstaller_path


    def _preflight_processes(self):
        """
        Start preflight processes
        """

        print("- Starting preflight processes")
        self._setup_pathing()
        self._delete_extra_binaries()
        self._download_resources()
        self._generate_payloads_dmg()


    def _postflight_processes(self):
        """
        Start postflight processes
        """

        print("- Starting postflight processes")
        self._patch_load_command()
        self._add_commit_data()
        self._post_flight_cleanup()
        self._mini_validate()


    def _build_binary(self):
        """
        Build binary via pyinstaller
        """

        if Path(f"./dist/OpenCore-Patcher.app").exists():
            print("- Found OpenCore-Patcher.app, removing...")
            rm_output = subprocess.run(
                ["rm", "-rf", "./dist/OpenCore-Patcher.app"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            if rm_output.returncode != 0:
                print("- Remove failed")
                print(rm_output.stderr.decode('utf-8'))
                raise Exception("Remove failed")


        print("- Building GUI binary...")
        build_args = [self.pyinstaller_path, "./OpenCore-Patcher-GUI.spec", "--noconfirm"]

        build_result = subprocess.run(build_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if build_result.returncode != 0:
            print("- Build failed")
            print(build_result.stderr.decode('utf-8'))
            raise Exception("Build failed")


    def _delete_extra_binaries(self):
        """
        Delete extra binaries from payloads directory
        """

        whitelist_folders = [
            "ACPI",
            "Config",
            "Drivers",
            "Icon",
            "InstallPackage",
            "Kexts",
            "OpenCore",
            "Tools",
        ]

        whitelist_files = [
            "com.sumingyd.opencore-legacy-patcher.auto-patch.plist",
            "entitlements.plist",
            "launcher.sh",
            "OC-Patcher-TUI.icns",
            "OC-Patcher.icns",
            "Universal-Binaries.zip",
        ]


        print("- Deleting extra binaries...")
        for file in Path("payloads").glob(pattern="*"):
            if file.is_dir():
                if file.name in whitelist_folders:
                    continue
                print(f"  - Deleting {file.name}")
                subprocess.run(["rm", "-rf", file])
            else:
                if file.name in whitelist_files:
                    continue
                print(f"  - Deleting {file.name}")
                subprocess.run(["rm", "-f", file])


    def _download_resources(self):
        """
        Download required dependencies
        """

        patcher_support_pkg_version = constants.Constants().patcher_support_pkg_version
        required_resources = [
            "Universal-Binaries.zip"
        ]

        print("- Downloading required resources...")
        for resource in required_resources:
            if Path(f"./payloads/{resource}").exists():
                if self.args.reset_binaries:
                    print(f"  - Removing old {resource}")
                    rm_output = subprocess.run(
                        ["rm", "-rf", f"./payloads/{resource}"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE
                    )
                    if rm_output.returncode != 0:
                        print("- Remove failed")
                        print(rm_output.stderr.decode('utf-8'))
                        raise Exception("Remove failed")
                else:
                    print(f"  - {resource} already exists, skipping download")
                    continue
            print(f"  - Downloading {resource}...")

            download_result = subprocess.run(
                [
                    "curl", "-LO",
                    f"https://github.com/sumingyd/PatcherSupportPkg/releases/download/{patcher_support_pkg_version}/{resource}"
                ],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )

            if download_result.returncode != 0:
                print("  - Download failed")
                print(download_result.stderr.decode('utf-8'))
                raise Exception("Download failed")
            if not Path(f"./{resource}").exists():
                print(f"  - {resource} not found")
                raise Exception(f"{resource} not found")

            print("  - Moving into payloads")
            mv_output = subprocess.run(["mv", resource, "./payloads/"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if mv_output.returncode != 0:
                print("  - Move failed")
                print(mv_output.stderr.decode('utf-8'))
                raise Exception("Move failed")


    def _generate_payloads_dmg(self):
        """
        Generate disk image containing all payloads
        Disk image will be password protected due to issues with
        Apple's notarization system and inclusion of kernel extensions
        """

        if Path("./payloads.dmg").exists():
            if not self.args.reset_binaries:
                print("  - payloads.dmg already exists, skipping creation")
                return

            print("  - Removing old payloads.dmg")
            rm_output = subprocess.run(
                ["rm", "-rf", "./payloads.dmg"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            if rm_output.returncode != 0:
                print("- Remove failed")
                print(rm_output.stderr.decode('utf-8'))
                raise Exception("Remove failed")

        print("  - Generating DMG...")
        dmg_output = subprocess.run([
            'hdiutil', 'create', './payloads.dmg',
            '-megabytes', '32000',
            '-format', 'UDZO', '-ov',
            '-volname', 'payloads',
            '-fs', 'HFS+',
            '-srcfolder', './payloads',
            '-passphrase', 'password', '-encryption'
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if dmg_output.returncode != 0:
            print("  - DMG generation failed")
            print(dmg_output.stderr.decode('utf-8'))
            raise Exception("DMG generation failed")

        print("  - DMG generation complete")


    def _add_commit_data(self):
        """
        Add commit data to Info.plist
        """

        if not self.args.branch and not self.args.commit and not self.args.commit_date:
            print("  - No commit data provided, adding source info")
            branch = "Built from source"
            commit_url = ""
            commit_date = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        else:
            branch = self.args.branch
            commit_url = self.args.commit
            commit_date = self.args.commit_date
        print("  - Adding commit data to Info.plist")
        plist_path = Path("./dist/OpenCore-Patcher.app/Contents/Info.plist")
        plist = plistlib.load(Path(plist_path).open("rb"))
        plist["Github"] = {
            "Branch": branch,
            "Commit URL": commit_url,
            "Commit Date": commit_date,
        }
        plistlib.dump(plist, Path(plist_path).open("wb"), sort_keys=True)


    def _patch_load_command(self):
        """
        Patch LC_VERSION_MIN_MACOSX in Load Command to report 10.10

        By default Pyinstaller will create binaries supporting 10.13+
        However this limitation is entirely arbitrary for our libraries
        and instead we're able to support 10.10 without issues.

        To verify set version:
          otool -l ./dist/OpenCore-Patcher.app/Contents/MacOS/OpenCore-Patcher

              cmd LC_VERSION_MIN_MACOSX
          cmdsize 16
          version 10.13
              sdk 10.9

        """

        print("  - Patching LC_VERSION_MIN_MACOSX")
        path = './dist/OpenCore-Patcher.app/Contents/MacOS/OpenCore-Patcher'
        find = b'\x00\x0D\x0A\x00' # 10.13 (0xA0D)
        replace = b'\x00\x0A\x0A\x00' # 10.10 (0xA0A)
        with open(path, 'rb') as f:
            data = f.read()
            data = data.replace(find, replace, 1)
            with open(path, 'wb') as f:
                f.write(data)


    def _post_flight_cleanup(self):
        """
        Post flight cleanup
        """

        path = "./dist/OpenCore-Patcher"
        print(f"  - Removing {path}")
        rm_output = subprocess.run(
            ["rm", "-rf", path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        if rm_output.returncode != 0:
            print(f"  - Remove failed: {path}")
            print(rm_output.stderr.decode('utf-8'))
            raise Exception(f"Remove failed: {path}")


    def _mini_validate(self):
        """
        Validate generated binary
        """

        print("  - Validating binary")
        validate_output = subprocess.run(
            ["./dist/OpenCore-Patcher.app/Contents/MacOS/OpenCore-Patcher", "--build", "--model", "MacPro3,1"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        if validate_output.returncode != 0:
            print("  - Validation failed")
            print(validate_output.stderr.decode('utf-8'))
            raise Exception("Validation failed")


if __name__ == "__main__":
    CreateBinary()