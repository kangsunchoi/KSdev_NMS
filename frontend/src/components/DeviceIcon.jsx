import React from "react";
import switchIcon from "../assets/device-icons/switch.png";
import l2SwitchIcon from "../assets/device-icons/l2-switch.png";
import l3SwitchIcon from "../assets/device-icons/l3-switch.png";
import routerIcon from "../assets/device-icons/router.png";
import serverIcon from "../assets/device-icons/server.png";
import storageIcon from "../assets/device-icons/storage.png";
import workstationIcon from "../assets/device-icons/workstation.png";
import accessPointIcon from "../assets/device-icons/access-point.png";
import wirelessControllerIcon from "../assets/device-icons/wireless-controller.png";

export const deviceIcons = {
  "switch": switchIcon,
  "l2-switch": l2SwitchIcon,
  "l3-switch": l3SwitchIcon,
  "router": routerIcon,
  "server": serverIcon,
  "storage": storageIcon,
  "workstation": workstationIcon,
  "access-point": accessPointIcon,
  "wireless-controller": wirelessControllerIcon,
};

export function DeviceIcon({ type }) {
  const src = deviceIcons[type];
  if (!src) return null;
  return <img src={src} alt="" title={type} width="24" height="24" className="mr-2 inline-block h-6 w-6 object-contain align-middle" />;
}
