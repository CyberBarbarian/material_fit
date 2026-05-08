// Unity Editor helper for exporting real material instance parameters.
// Place this file under a Unity project's Editor folder, then use:
// Material Fit/Export Selected Material Params

#if UNITY_EDITOR
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;

public static class MaterialFitUnityExporter
{
    [MenuItem("Material Fit/Export Selected Material Params", false, 1)]
    public static void ExportSelectedMaterialParams()
    {
        Material material = GetSelectedMaterial();
        if (material == null)
        {
            EditorUtility.DisplayDialog("Material Fit", "Please select a Material asset, or select a GameObject with a Renderer.", "OK");
            return;
        }

        string path = EditorUtility.SaveFilePanel("Export material params", Application.dataPath, material.name + "_params", "json");
        if (string.IsNullOrEmpty(path))
        {
            return;
        }

        Shader shader = material.shader;
        ExportData data = CreateExportData(material, shader);

        int propertyCount = shader != null ? shader.GetPropertyCount() : 0;
        for (int i = 0; i < propertyCount; i++)
        {
            string propertyName = shader.GetPropertyName(i);
            ShaderPropertyType propertyType = shader.GetPropertyType(i);
            ShaderPropertyFlags propertyFlags = shader.GetPropertyFlags(i);

            if (!material.HasProperty(propertyName))
            {
                data.missingProperties.Add(CreatePropertyMeta(shader, i, propertyName, propertyType, propertyFlags));
                continue;
            }

            if (propertyType == ShaderPropertyType.Color)
            {
                Color color = material.GetColor(propertyName);
                data.colors.Add(new ColorProperty
                {
                    name = propertyName,
                    displayName = shader.GetPropertyDescription(i),
                    flags = propertyFlags.ToString(),
                    value = ToArray(color)
                });
            }
            else if (propertyType == ShaderPropertyType.Vector)
            {
                Vector4 vector = material.GetVector(propertyName);
                data.vectors.Add(new VectorProperty
                {
                    name = propertyName,
                    displayName = shader.GetPropertyDescription(i),
                    flags = propertyFlags.ToString(),
                    value = ToArray(vector)
                });
            }
            else if (propertyType == ShaderPropertyType.Float || propertyType == ShaderPropertyType.Range)
            {
                FloatProperty property = new FloatProperty
                {
                    name = propertyName,
                    displayName = shader.GetPropertyDescription(i),
                    type = propertyType.ToString(),
                    flags = propertyFlags.ToString(),
                    value = material.GetFloat(propertyName)
                };

                if (propertyType == ShaderPropertyType.Range)
                {
                    Vector2 limits = shader.GetPropertyRangeLimits(i);
                    property.range = new float[] { limits.x, limits.y };
                }

                data.floats.Add(property);
            }
            else if (propertyType == ShaderPropertyType.Texture)
            {
                Texture texture = material.GetTexture(propertyName);
                string texturePath = texture != null ? AssetDatabase.GetAssetPath(texture) : string.Empty;
                data.textures.Add(new TextureProperty
                {
                    name = propertyName,
                    displayName = shader.GetPropertyDescription(i),
                    flags = propertyFlags.ToString(),
                    dimension = shader.GetPropertyTextureDimension(i).ToString(),
                    defaultTextureName = shader.GetPropertyTextureDefaultName(i),
                    textureName = texture != null ? texture.name : string.Empty,
                    textureAssetPath = texturePath,
                    textureGuid = string.IsNullOrEmpty(texturePath) ? string.Empty : AssetDatabase.AssetPathToGUID(texturePath),
                    scale = ToArray(material.GetTextureScale(propertyName)),
                    offset = ToArray(material.GetTextureOffset(propertyName))
                });
            }
            else
            {
                data.unsupportedProperties.Add(CreatePropertyMeta(shader, i, propertyName, propertyType, propertyFlags));
            }
        }

        // Use fully-qualified UnityEngine.JsonUtility here because some projects define
        // their own global JsonUtility class, which can shadow UnityEngine.JsonUtility
        // in older Unity projects and cause CS0117: 'JsonUtility' does not contain
        // a definition for 'ToJson'.
        File.WriteAllText(path, UnityEngine.JsonUtility.ToJson(data, true));
        AssetDatabase.Refresh();
        Debug.Log("Material params exported: " + path);
    }

    [MenuItem("Material Fit/Export Selected Material Params", true)]
    public static bool ValidateExportSelectedMaterialParams()
    {
        return GetSelectedMaterial() != null;
    }

    private static Material GetSelectedMaterial()
    {
        Material material = Selection.activeObject as Material;
        if (material != null)
        {
            return material;
        }

        GameObject gameObject = Selection.activeGameObject;
        if (gameObject == null)
        {
            return null;
        }

        Renderer renderer = gameObject.GetComponent<Renderer>();
        if (renderer == null || renderer.sharedMaterials == null || renderer.sharedMaterials.Length == 0)
        {
            return null;
        }

        return renderer.sharedMaterials[0];
    }

    private static ExportData CreateExportData(Material material, Shader shader)
    {
        string materialPath = AssetDatabase.GetAssetPath(material);
        string shaderPath = shader != null ? AssetDatabase.GetAssetPath(shader) : string.Empty;

        return new ExportData
        {
            exporterVersion = "1.0.0",
            exportedAtUtc = System.DateTime.UtcNow.ToString("o"),
            unityVersion = Application.unityVersion,
            materialName = material.name,
            materialAssetPath = materialPath,
            materialGuid = string.IsNullOrEmpty(materialPath) ? string.Empty : AssetDatabase.AssetPathToGUID(materialPath),
            shaderName = shader != null ? shader.name : string.Empty,
            shaderAssetPath = shaderPath,
            shaderGuid = string.IsNullOrEmpty(shaderPath) ? string.Empty : AssetDatabase.AssetPathToGUID(shaderPath),
            keywords = material.shaderKeywords,
            renderQueue = material.renderQueue,
            enableInstancing = material.enableInstancing,
            globalIlluminationFlags = material.globalIlluminationFlags.ToString()
        };
    }

    private static PropertyMeta CreatePropertyMeta(Shader shader, int index, string propertyName, ShaderPropertyType propertyType, ShaderPropertyFlags propertyFlags)
    {
        return new PropertyMeta
        {
            name = propertyName,
            displayName = shader.GetPropertyDescription(index),
            type = propertyType.ToString(),
            flags = propertyFlags.ToString()
        };
    }

    private static float[] ToArray(Color color)
    {
        return new float[] { color.r, color.g, color.b, color.a };
    }

    private static float[] ToArray(Vector4 vector)
    {
        return new float[] { vector.x, vector.y, vector.z, vector.w };
    }

    private static float[] ToArray(Vector2 vector)
    {
        return new float[] { vector.x, vector.y };
    }

    [System.Serializable]
    private class ExportData
    {
        public string exporterVersion = string.Empty;
        public string exportedAtUtc = string.Empty;
        public string unityVersion = string.Empty;
        public string materialName = string.Empty;
        public string materialAssetPath = string.Empty;
        public string materialGuid = string.Empty;
        public string shaderName = string.Empty;
        public string shaderAssetPath = string.Empty;
        public string shaderGuid = string.Empty;
        public string[] keywords = new string[0];
        public int renderQueue = -1;
        public bool enableInstancing = false;
        public string globalIlluminationFlags = string.Empty;
        public List<FloatProperty> floats = new List<FloatProperty>();
        public List<ColorProperty> colors = new List<ColorProperty>();
        public List<VectorProperty> vectors = new List<VectorProperty>();
        public List<TextureProperty> textures = new List<TextureProperty>();
        public List<PropertyMeta> missingProperties = new List<PropertyMeta>();
        public List<PropertyMeta> unsupportedProperties = new List<PropertyMeta>();
    }

    [System.Serializable]
    private class FloatProperty
    {
        public string name = string.Empty;
        public string displayName = string.Empty;
        public string type = string.Empty;
        public string flags = string.Empty;
        public float value = 0f;
        public float[] range = new float[0];
    }

    [System.Serializable]
    private class ColorProperty
    {
        public string name = string.Empty;
        public string displayName = string.Empty;
        public string flags = string.Empty;
        public float[] value = new float[4];
    }

    [System.Serializable]
    private class VectorProperty
    {
        public string name = string.Empty;
        public string displayName = string.Empty;
        public string flags = string.Empty;
        public float[] value = new float[4];
    }

    [System.Serializable]
    private class TextureProperty
    {
        public string name = string.Empty;
        public string displayName = string.Empty;
        public string flags = string.Empty;
        public string dimension = string.Empty;
        public string defaultTextureName = string.Empty;
        public string textureName = string.Empty;
        public string textureAssetPath = string.Empty;
        public string textureGuid = string.Empty;
        public float[] scale = new float[2];
        public float[] offset = new float[2];
    }

    [System.Serializable]
    private class PropertyMeta
    {
        public string name = string.Empty;
        public string displayName = string.Empty;
        public string type = string.Empty;
        public string flags = string.Empty;
    }
}
#endif
