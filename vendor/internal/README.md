# Laya prefab editor environment

This directory contains the prefab editor environment used by the packaged
runtime when an asset profile selects `laya_prefab_editor`. The files were
copied without modification from the local LayaAirIDE installation so Windows
and Linux load the same environment scene, sky material, and sky texture.

| File | SHA-256 |
| --- | --- |
| `DefaultPrefabEditEnv.ls` | `df7635d0811897e1ec7bc96022954ea0d3b8001ccd9b65ac77db1ad3b71244d5` |
| `DefaultPrefabEditEnv.ls.meta` | `36c5eb1370a2ef5002f6a6857e0c34250bf6734a8317aef1c6c1e831a392729c` |
| `DefaultSkyMaterial.lmat` | `de7dcb4e87efa4b0c821517feb81dd2275eec38d80b879d36a14c3007fb56183` |
| `DefaultSkyMaterial.lmat.meta` | `4813c7db25bc47e7064acf28e77291f4fb664bd9cb87f1f3266d4bdd1749d8d6` |
| `sky.jpg` | `9019d845676466611debe60c67299f1ca3edf0edbb6b367d54340b8a9b22b925` |
| `sky.jpg.meta` | `e66f9822a9ccf88cd9d9606fe039d210a80c31e24b52bff90f5e856e98b8922a` |

Stage 2 geometry alignment is applied to completed PNGs. These environment
files, the perspective camera, lights, and shaders are not calibration
variables.
