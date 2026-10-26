using AssetsTools.NET;
using AssetsTools.NET.Extra;
using AssetsTools.NET.Texture;
using SixLabors.ImageSharp;
using SixLabors.ImageSharp.PixelFormats;
using SixLabors.ImageSharp.Processing;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.RegularExpressions;
using AssetRipper.Conversions.Crunch;
using SixLabors.ImageSharp.Formats.Png;

// Read-only engine adapter. Uses the exact UABEA TexturePlugin channel/vertical conventions.
if (args.Length != 3) throw new ArgumentException("TextureExport <Data directory> <new export directory> <classdata.tpk>");
string input = Path.GetFullPath(args[0]), output = Path.GetFullPath(args[1]);
if (Directory.Exists(output)) throw new IOException("Refusing to overwrite an export snapshot");
Directory.CreateDirectory(output);
var provenance = new Dictionary<string, object>();
var files = new List<object>();
var failures = new List<object>();
var skipped = new List<object>();
var watch = System.Diagnostics.Stopwatch.StartNew();
string[] inputs = Directory.GetFiles(input).Where(p => p.EndsWith(".assets", StringComparison.OrdinalIgnoreCase)
    || Regex.IsMatch(Path.GetFileName(p), @"^level\d+$")).Order().ToArray();
int completed = 0;
foreach (string path in inputs)
{
    var manager = new AssetsManager();
    try
    {
        manager.LoadClassPackage(Path.GetFullPath(args[2]));
        var instance = manager.LoadAssetsFile(path, false);
        manager.LoadClassDatabaseFromPackage(instance.file.Metadata.UnityVersion);
        string sourceHash;
        using (var stream = File.OpenRead(path)) sourceHash = Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
        var textures = instance.file.Metadata.AssetInfos.Where(a => a.TypeId == 28).ToArray();
        files.Add(new { asset = Path.GetFileName(path), sha256 = sourceHash, textures = textures.Length, unity = instance.file.Metadata.UnityVersion });
        foreach (var info in textures)
        {
            try
            {
                var template = manager.GetTemplateBaseField(instance, instance.file.Reader, info.AbsoluteByteStart,
                    info.TypeId, instance.file.GetScriptIndex(info), AssetReadFlags.None);
                var imageField = template.Children.FirstOrDefault(f => f.Name == "image data");
                if (imageField != null) imageField.ValueType = AssetValueType.ByteArray;
                var field = template.MakeValue(instance.file.Reader, info.AbsoluteByteStart);
                var tex = TextureFile.ReadTextureFile(field);
                if (tex.m_Width <= 0 || tex.m_Height <= 0)
                {
                    skipped.Add(new { asset = Path.GetFileName(path), path_id = info.PathId, texture_name = tex.m_Name, reason = "zero_dimensions" });
                    continue;
                }
                byte[] bytes = tex.pictureData;
                if (tex.m_StreamData.size != 0 && !string.IsNullOrEmpty(tex.m_StreamData.path))
                {
                    string streamPath = tex.m_StreamData.path;
                    if (streamPath.StartsWith("archive:/")) streamPath = Path.GetFileName(streamPath);
                    streamPath = Path.GetFullPath(Path.Combine(Path.GetDirectoryName(path)!, streamPath));
                    if (!streamPath.StartsWith(input + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
                        throw new IOException("Texture stream outside game Data directory");
                    using var stream = File.OpenRead(streamPath);
                    stream.Position = checked((long)tex.m_StreamData.offset);
                    bytes = new byte[checked((int)tex.m_StreamData.size)];
                    stream.ReadExactly(bytes);
                }
                var format = (TextureFormat)tex.m_TextureFormat;
                if (format is TextureFormat.DXT1Crunched or TextureFormat.DXT5Crunched)
                {
                    if (!Crunch.TryDecompress(bytes, out byte[]? unpacked)) throw new IOException("Unity 5.x Crunch decompression failed");
                    bytes = unpacked;
                    format = format == TextureFormat.DXT1Crunched ? TextureFormat.DXT1 : TextureFormat.DXT5;
                }
                var decoded = TextureFile.DecodeManaged(bytes, format, tex.m_Width, tex.m_Height);
                if (decoded == null || decoded.Length < checked(tex.m_Width * tex.m_Height * 4)) throw new IOException("Texture decoder returned insufficient pixels");
                string safe = Regex.Replace(tex.m_Name, @"[^\p{L}\p{N}_.-]", "_");
                if (safe.Length > 90) safe = safe[..90];
                string name = $"{Path.GetFileName(path)}__{info.PathId}__{safe}.png";
                using var image = Image.LoadPixelData<Bgra32>(decoded.AsSpan(0, tex.m_Width * tex.m_Height * 4), tex.m_Width, tex.m_Height);
                image.Mutate(x => x.Flip(FlipMode.Vertical));
                image.SaveAsPng(Path.Combine(output, name), new PngEncoder { CompressionLevel = PngCompressionLevel.Level1 });
                provenance[name] = new { asset = Path.GetFileName(path), path_id = info.PathId,
                    texture_name = tex.m_Name, width = tex.m_Width, height = tex.m_Height,
                    texture_format = tex.m_TextureFormat, source_sha256 = sourceHash,
                    stream_path = tex.m_StreamData.path, stream_offset = tex.m_StreamData.offset,
                    stream_size = tex.m_StreamData.size, coordinate_origin = "top_left", decoder = "UABEA DecodeManaged BGRA + AssetRipper Unity5 Crunch + vertical flip" };
                if (provenance.Count % 100 == 0) Console.WriteLine($"textures={provenance.Count}; errors={failures.Count}; seconds={watch.Elapsed.TotalSeconds:F1}");
            }
            catch (Exception ex) { failures.Add(new { asset = Path.GetFileName(path), path_id = info.PathId, error = ex.ToString() }); }
        }
    }
    catch (Exception ex) { failures.Add(new { asset = Path.GetFileName(path), error = ex.ToString() }); }
    finally { manager.UnloadAllAssetsFiles(); }
    Console.WriteLine($"export {++completed}/{inputs.Length}; textures={provenance.Count}; errors={failures.Count}; seconds={watch.Elapsed.TotalSeconds:F1}");
    File.WriteAllText(Path.Combine(output, "provenance.json"), JsonSerializer.Serialize(provenance));
    File.WriteAllText(Path.Combine(output, "report.json"), JsonSerializer.Serialize(new { inputs = files, exported = provenance.Count, failures, skipped, elapsed_seconds = watch.Elapsed.TotalSeconds }));
}
