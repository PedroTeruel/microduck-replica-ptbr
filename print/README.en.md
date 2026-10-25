# Download print files from the CAD repository

[简体中文](README.md) · **English**

**Models, mechanical parts and printing projects are maintained in [fanhao375/microduck-replica-cad](https://github.com/fanhao375/microduck-replica-cad). Select the version matching your servos there.**

| Servo | Download |
|---|---|
| Feetech HD-1910 | [Feetech print resources](https://github.com/fanhao375/microduck-replica-cad#飞特-hd-1910-打印资料): 3MF print project, CAD sources and update notes |
| Dynamixel XL330 | [XL330 print resources](https://github.com/fanhao375/microduck-replica-cad#dynamixel-xl330-打印资料): matching CAD sources and printing instructions |
| Feetech shopping list | [Online preview](../BOM/README.md), including materials, quantities, recorded prices and purchase links |
| Assembly steps | [CAD assembly resources](https://github.com/fanhao375/microduck-replica-cad#装配资料与采购清单) |

**Do not mix mating parts from the Feetech and XL330 versions.** The old STLs here came from the upstream XL330 simulation model and did not include the Feetech CAD changes. They were removed on 2026-09-28 to prevent incorrect prints; Git history retains them for reference. This repository no longer maintains a second download copy of those models.

See the corresponding CAD sections for current files, update dates, printing materials and roller-variant notes. SolidWorks and STEP downloads are CAD sources; 3MF files are print projects. Check the servo version, printer and material before slicing.

Meshes retained in `software/training/` and the web servo console are for simulation/display, **not manufacturing**. Their geometry, mass and inertia have not been updated to match the latest physical CAD in this change.

CAD modelling and documentation are by **机械行者Robo**, under **CC BY-NC-SA 4.0** as derivatives of the upstream models. See the CAD repository for attribution, licensing and later versions.
