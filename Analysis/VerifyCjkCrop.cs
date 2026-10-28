using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text.RegularExpressions;
using System.Collections.Generic;
using Mono.Cecil;
using Mono.Cecil.Cil;

class VerifyCjkCrop {
    static string Operand(Instruction i,IList<Instruction> all,int offset) {
        if(i.Operand is Instruction) return "@"+(all.IndexOf((Instruction)i.Operand)-offset);
        if(i.Operand is Instruction[]) return String.Join(",",((Instruction[])i.Operand).Select(t=>(all.IndexOf(t)-offset).ToString()).ToArray());
        return i.Operand==null?"":i.Operand.ToString();
    }
    static string[] Body(MethodDefinition m,int skip) {
        if(!m.HasBody) return new string[0];
        return m.Body.Instructions.Skip(skip).Select(i=>i.OpCode+" "+Operand(i,m.Body.Instructions,skip)).ToArray();
    }
    static void Need(bool condition,string label) { if(!condition) throw new Exception(label); }
    static MethodInfo crop;
    static string Crop(string s,int n) { return (string)crop.Invoke(null,new object[]{s,n,"[...]"}); }
    static void Main(string[] args) {
        var before=AssemblyDefinition.ReadAssembly(args[0]); var after=AssemblyDefinition.ReadAssembly(args[1]);
        Need(before.MainModule.AssemblyReferences.Select(r=>r.FullName).SequenceEqual(after.MainModule.AssemblyReferences.Select(r=>r.FullName)),"Assembly references changed");
        var a=before.MainModule.GetTypes().SelectMany(t=>t.Methods).ToDictionary(m=>m.FullName);
        var b=after.MainModule.GetTypes().SelectMany(t=>t.Methods).ToDictionary(m=>m.FullName);
        Need(a.Keys.All(b.ContainsKey),"Existing method removed"); int changed=0;
        foreach(var k in a.Keys) {
            if(Body(a[k],0).SequenceEqual(Body(b[k],0))) continue;
            Need(a[k].DeclaringType.FullName=="InXile.Strings.StringCropper" && a[k].Name=="CropString","Unrelated method changed: "+k);
            Need(Body(a[k],0).SequenceEqual(Body(b[k],9)),"Original English method changed"); changed++;
        }
        Need(changed==1,"Expected one guarded entry point");
        Need(b.Keys.Except(a.Keys).All(k=>b[k].DeclaringType.FullName=="InXile.Strings.CjkRichTextCrop"),"Unexpected added method");
        var loaded=System.Reflection.Assembly.LoadFile(Path.GetFullPath(args[1]));
        var helper=loaded.GetType("InXile.Strings.CjkRichTextCrop",true);
        crop=helper.GetMethod("Crop",BindingFlags.Static|BindingFlags.NonPublic);
        var has=helper.GetMethod("HasCjk",BindingFlags.Static|BindingFlags.NonPublic);
        Need(!(bool)has.Invoke(null,new object[]{"English <color=#fff>description</color>"}),"English guard");
        Need((bool)has.Invoke(null,new object[]{"中文描述"}),"Chinese guard");
        string item=File.ReadAllText(args[2]);
        string composed=item+"\n\n<color=#C8C8C8FF>"+new string('\u4e2d',40)+"</color>";
        string old=Regex.Replace(composed.Substring(0,70),"\\s*\\W?\\b\\w*\\b$",String.Empty)+" [...]";
        Need(old.Contains("<color=") && !old.Contains("</color>"),"Original source-bound broken-tag reproduction");
        Need(!old.Contains("<color=#C8C8C8FF>"),"Original opening color tag is severed exactly as reported");
        string fixedText=Crop(composed,70);
        Need(fixedText.Contains("</color> [...]") && Regex.Replace(fixedText,"<[^>]+>","").Length==70+6,"Rich crop visible limit and tag closure");
        string shortRich=item+"\n\n<color=#C8C8C8FF>"+new string('\u4e2d',5)+"</color>";
        Need(shortRich.Length>70 && Crop(shortRich,70)==shortRich,"Markup length must not truncate short visible text");
        Need(Crop(new string('\u4e2d',71),70)==new string('\u4e2d',70)+" [...]","Chinese word boundary");
        Need(Crop("<color=red><b>中文测试</b></color>",2)=="<color=red><b>中文</b></color> [...]","Nested closure");
        Need(Crop("中文<quad material=0 size=16 />后",3)=="中文<quad material=0 size=16 /> [...]","Quad visible count");
        Need(Crop("中\uD83D\uDE00文",2)=="中\uD83D\uDE00 [...]","Surrogate boundary");
        Need(Crop("<b>中文</b>",2)=="<b>中文</b>","Exact limit closing tags");
        Need(Crop("<a id=42>中文测试</a>",2)=="<a id=42>中文</a> [...]","Game hyperlink closure");
        Need(Crop("",70)=="" && Crop(null,70)==null,"Empty input");
        Console.WriteLine("PASS: "+a.Count+" existing methods checked; only CJK crop prefix added; tutorial methods unchanged; assembly references unchanged.");
        Console.WriteLine("PASS: original screenshot-class failure reproduced offline; 9 rich-text/CJK/Unicode boundary cases passed on injected assembly helper.");
    }
}
