using AssetsTools.NET;
using AssetsTools.NET.Extra;
using SixLabors.ImageSharp;
using SixLabors.ImageSharp.PixelFormats;
using SixLabors.ImageSharp.Processing;
using System.Security.Cryptography;
using System.Text.Json;

// Isolated compatibility test only. Does not install or write game assets.
if (args.Length != 5) throw new ArgumentException("<source assets> <expected SHA256> <target definitions JSON> <new ImageText/engine_* directory> <classdata.tpk>");
string source = Path.GetFullPath(args[0]), expected = args[1].ToLowerInvariant();
string destination = Path.GetFullPath(args[3]);
string expectedParent = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../../"));
if (!source.EndsWith(".assets", StringComparison.OrdinalIgnoreCase) || !Path.GetFileName(destination).StartsWith("engine_", StringComparison.Ordinal)
    || !String.Equals(Path.GetDirectoryName(destination), expectedParent.TrimEnd(Path.DirectorySeparatorChar), StringComparison.OrdinalIgnoreCase)
    || Directory.Exists(destination))
    throw new IOException("Use a fresh engine_* test directory in this project's ImageText and an assets input");
static string Sha(string path) { using var s=File.OpenRead(path); return Convert.ToHexString(SHA256.HashData(s)).ToLowerInvariant(); }
if (Sha(source) != expected) throw new IOException("Source assets hash mismatch");
Directory.CreateDirectory(destination);
using var definitions = JsonDocument.Parse(File.ReadAllText(args[2]));
var targetItems = definitions.RootElement.GetProperty("targets").EnumerateArray().ToArray();
if (targetItems.Length == 0 || targetItems.Length > 32) throw new IOException("Test scope must have 1..32 explicit targets");
var targets = targetItems.ToDictionary(x => x.GetProperty("path_id").GetInt64());
var am = new AssetsManager();
am.LoadClassPackage(Path.GetFullPath(args[4]));
var inst = am.LoadAssetsFile(source, false);
am.LoadClassDatabaseFromPackage(inst.file.Metadata.UnityVersion);
var replacers = new List<AssetsReplacer>();
var changes = new List<object>();
foreach (var (id, target) in targets)
{
    string path = Path.GetFullPath(target.GetProperty("image").GetString() ?? throw new IOException("Image path missing"));
    var info = inst.file.GetAssetInfo(id) ?? throw new IOException($"Missing PathID {id}");
    if (info.TypeId != 28) throw new IOException($"Not Texture2D: {id}");
    var template = am.GetTemplateBaseField(inst, inst.file.Reader, info.AbsoluteByteStart,
        info.TypeId, inst.file.GetScriptIndex(info), AssetReadFlags.None);
    var imageTemplate = template.Children.FirstOrDefault(f => f.Name == "image data") ?? throw new IOException("No image data");
    imageTemplate.ValueType = AssetValueType.ByteArray;
    var field = template.MakeValue(inst.file.Reader, info.AbsoluteByteStart);
    int width=field["m_Width"].AsInt, height=field["m_Height"].AsInt, format=field["m_TextureFormat"].AsInt;
    int mip=field["m_MipCount"].AsInt;
    if (field["m_Name"].AsString != target.GetProperty("name").GetString()
        || format != target.GetProperty("original_format").GetInt32() || mip != 1
        || width != target.GetProperty("width").GetInt32() || height != target.GetProperty("height").GetInt32())
        throw new IOException($"Original name/format/mips/dimensions do not match target {id}");
    using var image=Image.Load<Rgba32>(path);
    if (image.Width != width || image.Height != height) throw new IOException($"PNG dimensions do not match {id}");
    image.Mutate(x => x.Flip(FlipMode.Vertical));
    var raw = new byte[checked(width*height*4)];
    image.CopyPixelDataTo(raw);
    field["m_StreamData"]["offset"].AsInt=0;
    field["m_StreamData"]["size"].AsInt=0;
    field["m_StreamData"]["path"].AsString="";
    field["m_TextureFormat"].AsInt=4; // Unity RGBA32; no lossy compression or Crunch encoder dependency.
    field["m_CompleteImageSize"].AsInt=raw.Length;
    field["m_MipCount"].AsInt=1;
    var data=field["image data"];
    data.Value.ValueType=AssetValueType.ByteArray;
    data.TemplateField.ValueType=AssetValueType.ByteArray;
    data.AsByteArray=raw;
    var bytes=field.WriteToByteArray();
    replacers.Add(new AssetsReplacerFromMemory(id, info.TypeId, inst.file.GetScriptIndex(info), bytes));
    changes.Add(new {path_id=id, width, height, old_format=format, new_format=4, mip_count=1,
                     image_sha256=Sha(path), original_stream_preserved=true, new_texture_embedded=true});
}
string output=Path.Combine(destination,Path.GetFileName(source));
using (var fs=File.Create(output)) using (var writer=new AssetsFileWriter(fs)) inst.file.Write(writer,0,replacers);
am.UnloadAllAssetsFiles();
if (Sha(source) != expected) throw new IOException("Source changed during test");
var a=new AssetsManager(); var b=new AssetsManager();
var original=a.LoadAssetsFile(source,false); var revised=b.LoadAssetsFile(output,false);
var before=original.file.Metadata.AssetInfos.ToDictionary(x=>x.PathId);
var after=revised.file.Metadata.AssetInfos.ToDictionary(x=>x.PathId);
if (before.Count != after.Count || before.Keys.Except(after.Keys).Any()) throw new IOException("Asset PathID set changed");
using var src=File.OpenRead(source); using var dst=File.OpenRead(output);
var left=new byte[65536]; var right=new byte[65536]; int compared=0;
foreach (var (id,x) in before)
{
    var y=after[id];
    if (x.TypeId != y.TypeId) throw new IOException($"Asset class changed: {id}");
    if (targets.ContainsKey(id)) continue;
    if (x.ByteSize != y.ByteSize) throw new IOException($"Unrelated asset length changed: {id}");
    src.Position=x.AbsoluteByteStart; dst.Position=y.AbsoluteByteStart;
    long remaining=x.ByteSize;
    while (remaining>0)
    {
        int n=(int)Math.Min(remaining,left.Length); src.ReadExactly(left.AsSpan(0,n)); dst.ReadExactly(right.AsSpan(0,n));
        if (!left.AsSpan(0,n).SequenceEqual(right.AsSpan(0,n))) throw new IOException($"Unrelated asset bytes changed: {id}");
        remaining-=n;
    }
    compared++;
}
a.UnloadAllAssetsFiles(); b.UnloadAllAssetsFiles();
var report = new { status="isolated_test_only", source_sha256=expected, output_sha256=Sha(output),
    asset_count=before.Count, unrelated_assets_byte_identical=compared, changes,
    source_modified=false, game_installed=false, runtime_tested=false };
File.WriteAllText(Path.Combine(destination,"report.json"),JsonSerializer.Serialize(report,new JsonSerializerOptions{WriteIndented=true}));
Console.WriteLine(JsonSerializer.Serialize(report));
