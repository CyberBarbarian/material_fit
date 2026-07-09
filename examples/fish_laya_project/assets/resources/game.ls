{
  "_$ver": 1,
  "_$id": "lx8mwule",
  "_$type": "Scene",
  "left": 0,
  "right": 0,
  "top": 0,
  "bottom": 0,
  "name": "Scene2D",
  "width": 1136,
  "height": 640,
  "mouseThrough": true,
  "autoDestroyAtClosed": true,
  "_$child": [
    {
      "_$id": "31l3k6zw",
      "_$type": "Scene3D",
      "name": "Scene3D",
      "ambientColor": {
        "_$type": "Color",
        "r": 0.212,
        "g": 0.227,
        "b": 0.259
      },
      "_$child": [
        {
          "_$id": "823p1d78",
          "_$type": "Camera",
          "name": "Capture Camera",
          "transform": {
            "localPosition": {
              "_$type": "Vector3",
              "y": -10
            }
          },
          "orthographic": true,
          "orthographicVerticalSize": 8,
          "fieldOfView": 41,
          "nearPlane": 0.3,
          "farPlane": 50,
          "clearFlag": 0,
          "clearColor": {
            "_$type": "Color",
            "r": 0,
            "g": 0,
            "b": 0,
            "a": 0
          },
          "postProcess": {
            "_$type": "PostProcess",
            "enable": false,
            "effects": [
              {
                "_$type": "BloomEffect",
                "clamp": 1,
                "color": {
                  "_$type": "Color"
                },
                "dirtIntensity": 0,
                "intensity": 4,
                "threshold": 0.8,
                "softKnee": 0.04,
                "diffusion": 4.5
              }
            ]
          },
          "_$comp": [
            {
              "_$type": "6610f67d-602e-4f03-af59-29460829b477",
              "scriptPath": "../src/MaterialFitCapture.ts",
              "serverBaseUrl": "http://127.0.0.1:8787",
              "cameraName": "Capture Camera",
              "targetName": "",
              "pollIntervalMs": 500,
              "autoPoll": true
            }
          ],
          "_$child": [
            {
              "_$id": "83j0rsuj",
              "_$type": "Sprite3D",
              "name": "model",
              "transform": {
                "localPosition": {
                  "_$type": "Vector3",
                  "y": -1,
                  "z": -10
                },
                "localScale": {
                  "_$type": "Vector3",
                  "x": 0.6000000238418579,
                  "y": 0.6000000238418579,
                  "z": 0.6000000238418579
                }
              },
              "_$comp": [
                {
                  "_$type": "Animator",
                  "controller": {
                    "_$uuid": "1960e5a8-d02f-4037-8009-19d7b0fa7f2b",
                    "_$type": "AnimationController"
                  },
                  "controllerLayers": [
                    {
                      "_$type": "AnimatorControllerLayer",
                      "name": "Base Layer",
                      "states": [
                        {
                          "_$type": "AnimatorState",
                          "name": "idle2",
                          "clipStart": 0,
                          "clip": {
                            "_$uuid": "9ec77d08-2b64-4bf8-8dc6-234b935790e0",
                            "_$type": "AnimationClip"
                          },
                          "soloTransitions": []
                        },
                        {
                          "_$type": "AnimatorState",
                          "name": "idle1",
                          "clipStart": 0,
                          "clip": {
                            "_$uuid": "392d198d-d1e9-4758-9ea4-a8cc5e229147",
                            "_$type": "AnimationClip"
                          },
                          "soloTransitions": []
                        }
                      ],
                      "defaultStateName": "idle1"
                    }
                  ]
                }
              ],
              "_$child": [
                {
                  "_$id": "29ecin44",
                  "_$type": "Sprite3D",
                  "name": "bone_00001",
                  "transform": {
                    "localPosition": {
                      "_$type": "Vector3",
                      "y": 1.752357,
                      "z": 7.659795e-8
                    },
                    "localRotation": {
                      "_$type": "Quaternion",
                      "x": -8.146033999999973e-8,
                      "w": -0.9999999999999967
                    }
                  },
                  "_$child": [
                    {
                      "_$id": "kjdggp7a",
                      "_$type": "Sprite3D",
                      "name": "Bone001",
                      "transform": {
                        "localPosition": {
                          "_$type": "Vector3",
                          "x": -1.577344,
                          "y": 0.3213702,
                          "z": -1.525879e-7
                        },
                        "localRotation": {
                          "_$type": "Quaternion",
                          "x": -5.961281039623385e-8,
                          "y": -3.7412870248675497e-10,
                          "z": -0.006275852041714272,
                          "w": -0.9999803066466594
                        }
                      },
                      "_$child": [
                        {
                          "_$id": "hgevwuy6",
                          "_$type": "Sprite3D",
                          "name": "Bone023",
                          "transform": {
                            "localPosition": {
                              "_$type": "Vector3",
                              "x": 0.1168727,
                              "y": -0.9719646,
                              "z": 2.288818e-7
                            },
                            "localRotation": {
                              "_$type": "Quaternion",
                              "x": 2.3809199915846828e-7,
                              "y": 1.247440995590943e-8,
                              "z": 0.9986302964703597,
                              "w": -0.05232141981507092
                            }
                          },
                          "_$child": [
                            {
                              "_$id": "6rmnp8zh",
                              "_$type": "Sprite3D",
                              "name": "collider",
                              "transform": {
                                "localPosition": {
                                  "_$type": "Vector3",
                                  "x": -1.444126844406128,
                                  "y": -0.46434512734413147,
                                  "z": 8.8904503604912e-14
                                },
                                "localRotation": {
                                  "_$type": "Quaternion",
                                  "x": -4.7235012532202345e-15,
                                  "y": 4.711989228434101e-15,
                                  "z": -1.5220698035278701e-9
                                }
                              },
                              "_$comp": [
                                {
                                  "_$type": "ed3900e7-62fc-4f1e-b8f2-4ed6b237106a",
                                  "scriptPath": "../src/Play/Fish/View/FishColliderOrthographic.ts",
                                  "radius": 1.2
                                }
                              ]
                            },
                            {
                              "_$id": "ue7wjh6d",
                              "_$type": "Sprite3D",
                              "name": "collider",
                              "transform": {
                                "localPosition": {
                                  "_$type": "Vector3",
                                  "x": 1.4332308769226074,
                                  "y": -0.46434521675109863,
                                  "z": 1.8231804141486535e-13
                                },
                                "localRotation": {
                                  "_$type": "Quaternion",
                                  "x": -4.7235012532202345e-15,
                                  "y": 4.711989228434101e-15,
                                  "z": -1.5220698035278701e-9
                                }
                              },
                              "_$comp": [
                                {
                                  "_$type": "ed3900e7-62fc-4f1e-b8f2-4ed6b237106a",
                                  "scriptPath": "../src/Play/Fish/View/FishColliderOrthographic.ts",
                                  "radius": 1
                                }
                              ]
                            }
                          ]
                        },
                        {
                          "_$id": "geapsl9o",
                          "_$type": "Sprite3D",
                          "name": "Bone027",
                          "transform": {
                            "localPosition": {
                              "_$type": "Vector3",
                              "x": 0.7993533,
                              "y": 0.7080398,
                              "z": 2.182787e-13
                            },
                            "localRotation": {
                              "_$type": "Quaternion",
                              "x": -1.5377040357298375e-8,
                              "y": -3.762995087436334e-9,
                              "z": -0.23770120552318602,
                              "w": -0.9713383225698571
                            }
                          }
                        },
                        {
                          "_$id": "pqxhmtty",
                          "_$type": "Sprite3D",
                          "name": "Bone028",
                          "transform": {
                            "localPosition": {
                              "_$type": "Vector3",
                              "x": 1.422904,
                              "y": -1.070238,
                              "z": -1.13695
                            },
                            "localRotation": {
                              "_$type": "Quaternion",
                              "x": -0.6678544071219094,
                              "y": 0.4937485052652675,
                              "z": 0.2960205031567228,
                              "w": 0.4717571050307542
                            }
                          }
                        },
                        {
                          "_$id": "h5pfx0wk",
                          "_$type": "Sprite3D",
                          "name": "Bone032",
                          "transform": {
                            "localPosition": {
                              "_$type": "Vector3",
                              "x": 1.448184,
                              "y": -1.108762,
                              "z": 1.137393
                            },
                            "localRotation": {
                              "_$type": "Quaternion",
                              "x": 0.4913681716744119,
                              "y": 0.30566088237976174,
                              "z": 0.4942211715099469,
                              "w": -0.6487481626020277
                            }
                          }
                        },
                        {
                          "_$id": "igpovedx",
                          "_$type": "Sprite3D",
                          "name": "Dummy001",
                          "transform": {
                            "localPosition": {
                              "_$type": "Vector3",
                              "x": 2.203355,
                              "y": 0.000002746582
                            },
                            "localRotation": {
                              "_$type": "Quaternion",
                              "x": -1.421096009463567e-14,
                              "y": 2.810937018718996e-17,
                              "z": 0.006275850041793044,
                              "w": -0.9999803066592128
                            }
                          },
                          "_$child": [
                            {
                              "_$id": "9fwgz3ch",
                              "_$type": "Sprite3D",
                              "name": "Bone002",
                              "transform": {
                                "localPosition": {
                                  "_$type": "Vector3",
                                  "x": 1.525879e-7
                                },
                                "localRotation": {
                                  "_$type": "Quaternion",
                                  "x": 2.3841230769309604e-7,
                                  "y": -1.9714320636142335e-9,
                                  "z": 0.004328438139670182,
                                  "w": -0.99999063226773
                                }
                              }
                            },
                            {
                              "_$id": "wl28nqlq",
                              "_$type": "Sprite3D",
                              "name": "Dummy003",
                              "transform": {
                                "localPosition": {
                                  "_$type": "Vector3",
                                  "x": 1.023278,
                                  "y": -0.009221343
                                },
                                "localRotation": {
                                  "_$type": "Quaternion",
                                  "x": -5.959997999999989e-8,
                                  "y": -5.56588099999999e-18,
                                  "z": 3.317263999999994e-25,
                                  "w": -0.9999999999999982
                                }
                              },
                              "_$child": [
                                {
                                  "_$id": "9luwuo8u",
                                  "_$type": "Sprite3D",
                                  "name": "Bone004",
                                  "transform": {
                                    "localPosition": {
                                      "_$type": "Vector3",
                                      "x": 1.525879e-7,
                                      "y": -1.525879e-7,
                                      "z": -1.611206e-7
                                    },
                                    "localRotation": {
                                      "_$type": "Quaternion",
                                      "x": -5.9593549999990404e-8,
                                      "y": -2.0034759999996776e-9,
                                      "z": 5.642599999999092e-7,
                                      "w": -0.999999999999839
                                    }
                                  }
                                },
                                {
                                  "_$id": "vdeaxvyt",
                                  "_$type": "Sprite3D",
                                  "name": "Dummy004",
                                  "transform": {
                                    "localPosition": {
                                      "_$type": "Vector3",
                                      "x": 0.2673351,
                                      "y": -0.00006652832,
                                      "z": 7.275957e-14
                                    },
                                    "localRotation": {
                                      "_$type": "Quaternion",
                                      "x": -1.294245e-32,
                                      "y": -1.165752e-16,
                                      "z": 1.110223e-16,
                                      "w": -1
                                    }
                                  },
                                  "_$child": [
                                    {
                                      "_$id": "sm8k8mft",
                                      "_$type": "Sprite3D",
                                      "name": "Bone005",
                                      "transform": {
                                        "localPosition": {
                                          "_$type": "Vector3",
                                          "x": 4.577637e-7,
                                          "y": -3.051758e-7,
                                          "z": -1.718193e-7
                                        },
                                        "localRotation": {
                                          "_$type": "Quaternion",
                                          "x": -1.1918729982333615e-7,
                                          "y": -4.0008269940698256e-9,
                                          "z": -0.00005444685991929684,
                                          "w": -0.9999999985177628
                                        }
                                      }
                                    },
                                    {
                                      "_$id": "wtvjxysf",
                                      "_$type": "Sprite3D",
                                      "name": "Dummy005",
                                      "transform": {
                                        "localPosition": {
                                          "_$type": "Vector3",
                                          "x": 0.6084183,
                                          "y": -0.000008392334,
                                          "z": -7.275957e-14
                                        },
                                        "localRotation": {
                                          "_$type": "Quaternion",
                                          "x": -6.164882e-34,
                                          "y": -5.552831e-18,
                                          "z": 1.110223e-16,
                                          "w": -1
                                        }
                                      },
                                      "_$comp": [
                                        {
                                          "_$type": "ed3900e7-62fc-4f1e-b8f2-4ed6b237106a",
                                          "scriptPath": "../src/Play/Fish/View/FishColliderOrthographic.ts",
                                          "radius": 0.8
                                        }
                                      ],
                                      "_$child": [
                                        {
                                          "_$id": "tbnxqv5c",
                                          "_$type": "Sprite3D",
                                          "name": "Bone006",
                                          "transform": {
                                            "localPosition": {
                                              "_$type": "Vector3",
                                              "x": 6.103515e-7,
                                              "y": -4.577637e-7,
                                              "z": -1.887569e-7
                                            },
                                            "localRotation": {
                                              "_$type": "Quaternion",
                                              "x": -1.7859140608584401e-7,
                                              "y": -1.0184490347056002e-8,
                                              "z": 0.023355030795867378,
                                              "w": -0.9997272340676191
                                            }
                                          }
                                        },
                                        {
                                          "_$id": "cy44t59x",
                                          "_$type": "Sprite3D",
                                          "name": "Dummy006",
                                          "transform": {
                                            "localPosition": {
                                              "_$type": "Vector3",
                                              "x": 0.59001,
                                              "y": -0.02757736,
                                              "z": 1.455191e-13
                                            },
                                            "localRotation": {
                                              "_$type": "Quaternion",
                                              "x": -1.421086e-14,
                                              "y": 4.995843e-17,
                                              "z": -7.09952e-31,
                                              "w": -1
                                            }
                                          },
                                          "_$child": [
                                            {
                                              "_$id": "xsn2fps7",
                                              "_$type": "Sprite3D",
                                              "name": "Bone007",
                                              "transform": {
                                                "localPosition": {
                                                  "_$type": "Vector3",
                                                  "x": 6.103515e-7,
                                                  "y": -6.103515e-7,
                                                  "z": -2.267072e-7
                                                },
                                                "localRotation": {
                                                  "_$type": "Quaternion",
                                                  "x": -2.3787619922860753e-7,
                                                  "y": -1.0790189965009231e-8,
                                                  "z": -0.04531391985305459,
                                                  "w": -0.9989727967604994
                                                }
                                              }
                                            },
                                            {
                                              "_$id": "xh19wcfb",
                                              "_$type": "Sprite3D",
                                              "name": "Dummy007",
                                              "transform": {
                                                "localPosition": {
                                                  "_$type": "Vector3",
                                                  "x": 0.4055841,
                                                  "y": 0.03687088,
                                                  "z": 1.525878e-7
                                                },
                                                "localRotation": {
                                                  "_$type": "Quaternion",
                                                  "y": -5.552672e-18,
                                                  "w": -1
                                                }
                                              },
                                              "_$child": [
                                                {
                                                  "_$id": "4m5wi3md",
                                                  "_$type": "Sprite3D",
                                                  "name": "Bone008",
                                                  "transform": {
                                                    "localPosition": {
                                                      "_$type": "Vector3",
                                                      "x": 6.103515e-7,
                                                      "y": -7.629394e-7,
                                                      "z": -2.405397e-7
                                                    },
                                                    "localRotation": {
                                                      "_$type": "Quaternion",
                                                      "x": -2.9632520201123374e-7,
                                                      "y": -2.8266980191855108e-8,
                                                      "z": 0.015867280107695222,
                                                      "w": -0.9998741067863971
                                                    }
                                                  }
                                                },
                                                {
                                                  "_$id": "inqmbxso",
                                                  "_$type": "Sprite3D",
                                                  "name": "Dummy008",
                                                  "transform": {
                                                    "localPosition": {
                                                      "_$type": "Vector3",
                                                      "x": 0.5807483,
                                                      "y": -0.01845108,
                                                      "z": -1.525878e-7
                                                    },
                                                    "localRotation": {
                                                      "_$type": "Quaternion",
                                                      "x": 1.421086e-14,
                                                      "y": -5.552672e-18,
                                                      "z": 1.110223e-16,
                                                      "w": -1
                                                    }
                                                  },
                                                  "_$child": [
                                                    {
                                                      "_$id": "bpxrxqzl",
                                                      "_$type": "Sprite3D",
                                                      "name": "Bone009",
                                                      "transform": {
                                                        "localPosition": {
                                                          "_$type": "Vector3",
                                                          "x": 6.103515e-7,
                                                          "y": -0.000001068115,
                                                          "z": -1.468271e-7
                                                        },
                                                        "localRotation": {
                                                          "_$type": "Quaternion",
                                                          "x": -3.5687930438896597e-7,
                                                          "y": -1.6182180199011367e-8,
                                                          "z": -0.026306950323527614,
                                                          "w": -0.9996539122939239
                                                        }
                                                      }
                                                    },
                                                    {
                                                      "_$id": "28jh4ydb",
                                                      "_$type": "Sprite3D",
                                                      "name": "Dummy009",
                                                      "transform": {
                                                        "localPosition": {
                                                          "_$type": "Vector3",
                                                          "x": 0.3502997,
                                                          "y": 0.01841751,
                                                          "z": 1.525878e-7
                                                        },
                                                        "localRotation": {
                                                          "_$type": "Quaternion",
                                                          "x": 1.421086e-14,
                                                          "y": -5.552672e-18,
                                                          "z": 1.110223e-16,
                                                          "w": -1
                                                        }
                                                      },
                                                      "_$child": [
                                                        {
                                                          "_$id": "f4swea3g",
                                                          "_$type": "Sprite3D",
                                                          "name": "Bone010",
                                                          "transform": {
                                                            "localRotation": {
                                                              "_$type": "Quaternion",
                                                              "z": 0.01509108883837987,
                                                              "w": -0.9998861230348545
                                                            }
                                                          }
                                                        },
                                                        {
                                                          "_$id": "82c7cslb",
                                                          "_$type": "Sprite3D",
                                                          "name": "Bone011",
                                                          "transform": {
                                                            "localPosition": {
                                                              "_$type": "Vector3",
                                                              "x": 0.3108878,
                                                              "y": -0.01560348,
                                                              "z": 7.275957e-14
                                                            },
                                                            "localRotation": {
                                                              "_$type": "Quaternion",
                                                              "x": -1.1920459999999577e-7,
                                                              "y": 2.840047999999899e-14,
                                                              "z": 2.384185999999915e-7,
                                                              "w": -0.9999999999999645
                                                            }
                                                          },
                                                          "_$comp": [
                                                            {
                                                              "_$type": "ed3900e7-62fc-4f1e-b8f2-4ed6b237106a",
                                                              "scriptPath": "../src/Play/Fish/View/FishColliderOrthographic.ts",
                                                              "radius": 0.8
                                                            }
                                                          ]
                                                        }
                                                      ]
                                                    }
                                                  ]
                                                }
                                              ]
                                            }
                                          ]
                                        }
                                      ]
                                    }
                                  ]
                                }
                              ]
                            }
                          ]
                        }
                      ]
                    }
                  ]
                },
                {
                  "_$id": "w6b2tp7m",
                  "_$type": "Sprite3D",
                  "name": "fish_jxs",
                  "transform": {
                    "localPosition": {
                      "_$type": "Vector3",
                      "z": 9.368768e-8
                    }
                  },
                  "_$comp": [
                    {
                      "_$type": "MeshFilter",
                      "sharedMesh": {
                        "_$uuid": "26d79d19-fe9f-405e-b7cb-4a7fc75b7d92",
                        "_$type": "Mesh"
                      }
                    },
                    {
                      "_$type": "SkinnedMeshRenderer",
                      "receiveShadow": true,
                      "castShadow": true,
                      "lightmapScaleOffset": {
                        "_$type": "Vector4"
                      },
                      "sharedMaterials": [
                        {
                          "_$uuid": "4adc3c2d-41bc-4cad-87df-77ecfb84a558",
                          "_$type": "Material"
                        }
                      ],
                      "_bones": [
                        {
                          "_$ref": "kjdggp7a"
                        },
                        {
                          "_$ref": "hgevwuy6"
                        },
                        {
                          "_$ref": "h5pfx0wk"
                        },
                        {
                          "_$ref": "pqxhmtty"
                        },
                        {
                          "_$ref": "geapsl9o"
                        },
                        {
                          "_$ref": "9fwgz3ch"
                        },
                        {
                          "_$ref": "9luwuo8u"
                        },
                        {
                          "_$ref": "sm8k8mft"
                        },
                        {
                          "_$ref": "tbnxqv5c"
                        },
                        {
                          "_$ref": "xsn2fps7"
                        },
                        {
                          "_$ref": "4m5wi3md"
                        },
                        {
                          "_$ref": "bpxrxqzl"
                        },
                        {
                          "_$ref": "28jh4ydb"
                        },
                        {
                          "_$ref": "f4swea3g"
                        },
                        {
                          "_$ref": "82c7cslb"
                        }
                      ],
                      "rootBone": {
                        "_$ref": "kjdggp7a"
                      },
                      "localBounds": {
                        "_$type": "Bounds",
                        "min": {
                          "_$type": "Vector3",
                          "x": -3.283696,
                          "y": -2.060432,
                          "z": -2.763393
                        },
                        "max": {
                          "_$type": "Vector3",
                          "x": 8.387234,
                          "y": 2.283225,
                          "z": 2.78144
                        }
                      }
                    }
                  ]
                }
              ]
            }
          ]
        },
        {
          "_$id": "zc3f6ecn",
          "_$type": "Sprite3D",
          "name": "DirectionLight",
          "transform": {
            "localPosition": {
              "_$type": "Vector3",
              "z": 5
            }
          },
          "_$comp": [
            {
              "_$type": "DirectionLightCom",
              "lightmapBakedType": 0,
              "strength": 1,
              "angle": 0.526,
              "maxBounces": 1024
            }
          ]
        }
      ]
    }
  ]
}
