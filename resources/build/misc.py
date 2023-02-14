# Class for handling Misc Patches, invocation from build.py
# Copyright (C) 2020-2022, Dhinak G, Mykola Grymalyuk

from resources import constants, device_probe, generate_smbios, utilities
from resources.build import support
from data import model_array, smbios_data, cpu_data

import binascii, shutil, logging
from pathlib import Path


class build_misc:

    def __init__(self, model, versions, config):
        self.model = model
        self.constants: constants.Constants = versions
        self.config = config
        self.computer = self.constants.computer

    def rmtree_handler(func, path, exc_info):
        if exc_info[0] == FileNotFoundError:
            return
        raise  # pylint: disable=misplaced-bare-raise

    def build(self):
        self.feature_unlock_handling()
        self.restrict_events_handling()
        self.firewire_handling()
        self.trackpad_handling()
        self.thunderbolt_handling()
        self.webcam_handling()
        self.usb_handling()
        self.debug_handling()
        self.cpu_friend_handling()
        self.general_oc_handling()

    def feature_unlock_handling(self):
        if self.constants.fu_status is True:
            support.build_support(self.model, self.constants, self.config).enable_kext("FeatureUnlock.kext", self.constants.featureunlock_version, self.constants.featureunlock_path)
            if self.constants.fu_arguments is not None:
                logging.info(f"- Adding additional FeatureUnlock args: {self.constants.fu_arguments}")
                self.config["NVRAM"]["Add"]["7C436110-AB2A-4BBB-A880-FE41995C9F82"]["boot-args"] += self.constants.fu_arguments

    def restrict_events_handling(self):
        # RestrictEvents handling
        # - revpatch: Process patching
        # - revblock: Process blocking
        block_args = ""
        if self.model in ["MacBookPro6,1", "MacBookPro6,2", "MacBookPro9,1", "MacBookPro10,1"]:
            block_args += "gmux,"
        if self.model in model_array.MacPro:
            logging.info("- Disabling memory error reporting")
            block_args += "pcie,"
        gpu_dict = []
        if not self.constants.custom_model:
            gpu_dict = self.constants.computer.gpus
        else:
            if self.model in smbios_data.smbios_dictionary:
                gpu_dict = smbios_data.smbios_dictionary[self.model]["Stock GPUs"]
        for gpu in gpu_dict:
            if not self.constants.custom_model:
                gpu = gpu.arch
            if gpu in [
                device_probe.Intel.Archs.Ivy_Bridge,
                device_probe.Intel.Archs.Haswell,
                device_probe.NVIDIA.Archs.Kepler,
            ]:
                logging.info("- Disabling mediaanalysisd")
                block_args += "media,"
                break
        if block_args.endswith(","):
            block_args = block_args[:-1]

        if block_args != "":
            logging.info(f"- Setting RestrictEvents block arguments: {block_args}")
            support.build_support(self.model, self.constants, self.config).enable_kext("RestrictEvents.kext", self.constants.restrictevents_version, self.constants.restrictevents_path)
            self.config["NVRAM"]["Add"]["4D1FDA02-38C7-4A6A-9CC6-4BCCA8B30102"]["revblock"] = block_args

        patch_args = ""
        if support.build_support(self.model, self.constants, self.config).get_item_by_kv(self.config["Kernel"]["Patch"], "Comment", "Reroute kern.hv_vmm_present patch (1)")["Enabled"] is True and self.constants.set_content_caching is True:
            logging.info("- Fixing Content Caching support")
            patch_args += "asset,"

        if patch_args.endswith(","):
            patch_args = patch_args[:-1]

        if block_args != "" and patch_args == "":
            # Disable unneeded Userspace patching (cs_validate_page is quite expensive)
            patch_args = "none"

        if patch_args != "":
            logging.info(f"- Setting RestrictEvents patch arguments: {patch_args}")
            support.build_support(self.model, self.constants, self.config).enable_kext("RestrictEvents.kext", self.constants.restrictevents_version, self.constants.restrictevents_path)
            self.config["NVRAM"]["Add"]["4D1FDA02-38C7-4A6A-9CC6-4BCCA8B30102"]["revpatch"] = patch_args

        if self.constants.custom_cpu_model == 0 or self.constants.custom_cpu_model == 1:
            self.config["NVRAM"]["Add"]["4D1FDA02-38C7-4A6A-9CC6-4BCCA8B30102"]["revcpu"] = self.constants.custom_cpu_model
            if self.constants.custom_cpu_model_value != "":
                logging.info(f"- Adding custom CPU Name: {self.constants.custom_cpu_model_value}")
                self.config["NVRAM"]["Add"]["4D1FDA02-38C7-4A6A-9CC6-4BCCA8B30102"]["revcpuname"] = self.constants.custom_cpu_model_value
            else:
                logging.info("- Adding CPU Name Patch")
            support.build_support(self.model, self.constants, self.config).enable_kext("RestrictEvents.kext", self.constants.restrictevents_version, self.constants.restrictevents_path)

        if support.build_support(self.model, self.constants, self.config).get_kext_by_bundle_path("RestrictEvents.kext")["Enabled"] is False:
            # Ensure this is done at the end so all previous RestrictEvents patches are applied
            # RestrictEvents and EFICheckDisabler will conflict if both are injected
            support.build_support(self.model, self.constants, self.config).enable_kext("EFICheckDisabler.kext", "", self.constants.efi_disabler_path)


    def cpu_friend_handling(self):
        if self.model not in ["iMac7,1", "Xserve2,1", "sumingyd1,1"] and self.constants.disallow_cpufriend is False and self.constants.serial_settings != "None":
            support.build_support(self.model, self.constants, self.config).enable_kext("CPUFriend.kext", self.constants.cpufriend_version, self.constants.cpufriend_path)

            # CPUFriendDataProvider handling
            pp_map_path = Path(self.constants.platform_plugin_plist_path) / Path(f"{self.model}/Info.plist")
            if not pp_map_path.exists():
                raise Exception(f"{pp_map_path} does not exist!!! Please file an issue stating file is missing for {self.model}.")
            Path(self.constants.pp_kext_folder).mkdir()
            Path(self.constants.pp_contents_folder).mkdir()
            shutil.copy(pp_map_path, self.constants.pp_contents_folder)
            support.build_support(self.model, self.constants, self.config).get_kext_by_bundle_path("CPUFriendDataProvider.kext")["Enabled"] = True

    def firewire_handling(self):
        if self.constants.firewire_boot is True and generate_smbios.check_firewire(self.model) is True:
            # Enable FireWire Boot Support
            # Applicable for both native FireWire and Thunderbolt to FireWire adapters
            logging.info("- Enabling FireWire Boot Support")
            support.build_support(self.model, self.constants, self.config).enable_kext("IOFireWireFamily.kext", self.constants.fw_kext, self.constants.fw_family_path)
            support.build_support(self.model, self.constants, self.config).enable_kext("IOFireWireSBP2.kext", self.constants.fw_kext, self.constants.fw_sbp2_path)
            support.build_support(self.model, self.constants, self.config).enable_kext("IOFireWireSerialBusProtocolTransport.kext", self.constants.fw_kext, self.constants.fw_bus_path)
            support.build_support(self.model, self.constants, self.config).get_kext_by_bundle_path("IOFireWireFamily.kext/Contents/PlugIns/AppleFWOHCI.kext")["Enabled"] = True

    def trackpad_handling(self):
        # Pre-Force Touch trackpad support for macOS Ventura
        if smbios_data.smbios_dictionary[self.model]["CPU Generation"] < cpu_data.cpu_data.skylake.value:
            if self.model.startswith("MacBook"):
                # These units got force touch early, so ignore them
                if self.model not in ["MacBookPro11,4", "MacBookPro11,5", "MacBookPro12,1", "MacBook8,1"]:
                    support.build_support(self.model, self.constants, self.config).enable_kext("AppleUSBTopCase.kext", self.constants.topcase_version, self.constants.top_case_path)
                    support.build_support(self.model, self.constants, self.config).get_kext_by_bundle_path("AppleUSBTopCase.kext/Contents/PlugIns/AppleUSBTCButtons.kext")["Enabled"] = True
                    support.build_support(self.model, self.constants, self.config).get_kext_by_bundle_path("AppleUSBTopCase.kext/Contents/PlugIns/AppleUSBTCKeyboard.kext")["Enabled"] = True
                    support.build_support(self.model, self.constants, self.config).get_kext_by_bundle_path("AppleUSBTopCase.kext/Contents/PlugIns/AppleUSBTCKeyEventDriver.kext")["Enabled"] = True
                    support.build_support(self.model, self.constants, self.config).enable_kext("AppleUSBMultitouch.kext", self.constants.multitouch_version, self.constants.multitouch_path)
        # Legacy Trackpad support
        if self.model in ["MacBook4,1", "MacBook5,2"]:
            support.build_support(self.model, self.constants, self.config).enable_kext("AppleUSBTrackpad.kext", self.constants.apple_trackpad, self.constants.apple_trackpad_path)

    def thunderbolt_handling(self):
        if self.constants.disable_tb is True and self.model in ["MacBookPro11,1", "MacBookPro11,2", "MacBookPro11,3", "MacBookPro11,4", "MacBookPro11,5"]:
            logging.info("- Disabling 2013-2014 laptop Thunderbolt Controller")
            if self.model in ["MacBookPro11,3", "MacBookPro11,5"]:
                # 15" dGPU models: IOACPIPlane:/_SB/PCI0@0/PEG1@10001/UPSB@0/DSB0@0/NHI0@0
                tb_device_path = "PciRoot(0x0)/Pci(0x1,0x1)/Pci(0x0,0x0)/Pci(0x0,0x0)/Pci(0x0,0x0)"
            else:
                # 13" and 15" iGPU 2013-2014 models: IOACPIPlane:/_SB/PCI0@0/P0P2@10000/UPSB@0/DSB0@0/NHI0@0
                tb_device_path = "PciRoot(0x0)/Pci(0x1,0x0)/Pci(0x0,0x0)/Pci(0x0,0x0)/Pci(0x0,0x0)"

            self.config["DeviceProperties"]["Add"][tb_device_path] = {"class-code": binascii.unhexlify("FFFFFFFF"), "device-id": binascii.unhexlify("FFFF0000")}

    def webcam_handling(self):
        # Legacy iSight patches
        if "Legacy iSight" in smbios_data.smbios_dictionary[self.model]:
            if smbios_data.smbios_dictionary[self.model]["Legacy iSight"] is True:
                support.build_support(self.model, self.constants, self.config).enable_kext("LegacyUSBVideoSupport.kext", self.constants.apple_isight_version, self.constants.apple_isight_path)

    def usb_handling(self):
        # USB Map
        usb_map_path = Path(self.constants.plist_folder_path) / Path("AppleUSBMaps/Info.plist")
        if (
            usb_map_path.exists()
            and (self.constants.allow_oc_everywhere is False or self.constants.allow_native_spoofs is True)
            and self.model not in ["Xserve2,1", "sumingyd1,1"]
            and (
                (self.model in model_array.Missing_USB_Map or self.model in model_array.Missing_USB_Map_Ventura)
                or self.constants.serial_settings in ["Moderate", "Advanced"])
        ):
            logging.info("- Adding USB-Map.kext")
            Path(self.constants.map_kext_folder).mkdir()
            Path(self.constants.map_contents_folder).mkdir()
            shutil.copy(usb_map_path, self.constants.map_contents_folder)
            support.build_support(self.model, self.constants, self.config).get_kext_by_bundle_path("USB-Map.kext")["Enabled"] = True
            if self.model in model_array.Missing_USB_Map_Ventura and self.constants.serial_settings not in ["Moderate", "Advanced"]:
                support.build_support(self.model, self.constants, self.config).get_kext_by_bundle_path("USB-Map.kext")["MinKernel"] = "22.0.0"

        # Add UHCI/OHCI drivers
        # All Penryn Macs lack an internal USB hub to route USB 1.1 devices to the EHCI controller
        # And MacPro4,1 and MacPro5,1 are the only post-Penryn Macs that lack an internal USB hub
        # - Ref: https://techcommunity.microsoft.com/t5/microsoft-usb-blog/reasons-to-avoid-companion-controllers/ba-p/270710
        #
        # Required downgrades:
        #  - IOUSBHostFamily.kext (only kext itself, not plugins)
        #  - AppleUSBHub.kext
        #  - AppleUSBEHCI.kext
        if (
            smbios_data.smbios_dictionary[self.model]["CPU Generation"] <= cpu_data.cpu_data.penryn.value or \
            self.model in ["MacPro4,1", "MacPro5,1"]
        ):
            logging.info("- Adding UHCI/OHCI USB support")
            shutil.copy(self.constants.apple_usb_11_injector_path, self.constants.kexts_path)
            support.build_support(self.model, self.constants, self.config).get_kext_by_bundle_path("USB1.1-Injector.kext/Contents/PlugIns/AppleUSBOHCI.kext")["Enabled"] = True
            support.build_support(self.model, self.constants, self.config).get_kext_by_bundle_path("USB1.1-Injector.kext/Contents/PlugIns/AppleUSBOHCIPCI.kext")["Enabled"] = True
            support.build_support(self.model, self.constants, self.config).get_kext_by_bundle_path("USB1.1-Injector.kext/Contents/PlugIns/AppleUSBUHCI.kext")["Enabled"] = True
            support.build_support(self.model, self.constants, self.config).get_kext_by_bundle_path("USB1.1-Injector.kext/Contents/PlugIns/AppleUSBUHCIPCI.kext")["Enabled"] = True

    def debug_handling(self):
        # DEBUG Settings (OpenCorePkg and Kernel Space)

        if self.constants.verbose_debug is True:
            logging.info("- Enabling Verbose boot")
            self.config["NVRAM"]["Add"]["7C436110-AB2A-4BBB-A880-FE41995C9F82"]["boot-args"] += " -v"

        if self.constants.kext_debug is True:
            logging.info("- Enabling DEBUG Kexts")
            self.config["NVRAM"]["Add"]["7C436110-AB2A-4BBB-A880-FE41995C9F82"]["boot-args"] += " -liludbgall liludump=90"
            # Disabled due to macOS Monterey crashing shortly after kernel init
            # Use DebugEnhancer.kext instead
            # self.config["NVRAM"]["Add"]["7C436110-AB2A-4BBB-A880-FE41995C9F82"]["boot-args"] += " msgbuf=1048576"
            support.build_support(self.model, self.constants, self.config).enable_kext("DebugEnhancer.kext", self.constants.debugenhancer_version, self.constants.debugenhancer_path)

        if self.constants.opencore_debug is True:
            logging.info("- Enabling DEBUG OpenCore")
            self.config["Misc"]["Debug"]["Target"] = 0x43
            self.config["Misc"]["Debug"]["DisplayLevel"] = 0x80000042

    def general_oc_handling(self):
        # OpenCorePkg Settings

        # OpenCanopy Settings (GUI)
        logging.info("- Adding OpenCanopy GUI")
        shutil.rmtree(self.constants.resources_path, onerror=self.rmtree_handler)
        shutil.copy(self.constants.gui_path, self.constants.oc_folder)
        support.build_support(self.model, self.constants, self.config).get_efi_binary_by_path("OpenCanopy.efi", "UEFI", "Drivers")["Enabled"] = True
        support.build_support(self.model, self.constants, self.config).get_efi_binary_by_path("OpenRuntime.efi", "UEFI", "Drivers")["Enabled"] = True
        support.build_support(self.model, self.constants, self.config).get_efi_binary_by_path("OpenLinuxBoot.efi", "UEFI", "Drivers")["Enabled"] = True
        support.build_support(self.model, self.constants, self.config).get_efi_binary_by_path("ResetNvramEntry.efi", "UEFI", "Drivers")["Enabled"] = True

        if self.constants.showpicker is False:
            logging.info("- Hiding OpenCore picker")
            self.config["Misc"]["Boot"]["ShowPicker"] = False

        if self.constants.oc_timeout != 5:
            logging.info(f"- Setting custom OpenCore picker timeout to {self.constants.oc_timeout} seconds")
            self.config["Misc"]["Boot"]["Timeout"] = self.constants.oc_timeout

        if self.constants.vault is True and utilities.check_command_line_tools() is True:
            logging.info("- Setting Vault configuration")
            self.config["Misc"]["Security"]["Vault"] = "Secure"
            support.build_support(self.model, self.constants, self.config).get_efi_binary_by_path("OpenShell.efi", "Misc", "Tools")["Enabled"] = False