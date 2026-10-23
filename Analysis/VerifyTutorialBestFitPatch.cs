using System;
using System.Linq;
using System.Collections.Generic;
using Mono.Cecil;
using Mono.Cecil.Cil;
class VerifyTutorialBestFitPatch {
    static string Operand(Instruction i, IList<Instruction> all) {
        if(i.Operand is Instruction) return "@"+all.IndexOf((Instruction)i.Operand);
        if(i.Operand is Instruction[]) return String.Join(",",((Instruction[])i.Operand).Select(t=>all.IndexOf(t).ToString()).ToArray());
        return i.Operand==null?"":i.Operand.ToString();
    }
    static string[] Body(MethodDefinition m) {
        if(!m.HasBody)return new string[0];
        return m.Body.Instructions.Select(i=>i.OpCode+" "+Operand(i,m.Body.Instructions)).ToArray();
    }
    static void Main(string[] args) {
        var a=AssemblyDefinition.ReadAssembly(args[0]);var b=AssemblyDefinition.ReadAssembly(args[1]);
        var before=a.MainModule.GetTypes().SelectMany(t=>t.Methods).ToDictionary(m=>m.FullName);
        var after=b.MainModule.GetTypes().SelectMany(t=>t.Methods).ToDictionary(m=>m.FullName);
        if(!before.Keys.OrderBy(x=>x).SequenceEqual(after.Keys.OrderBy(x=>x)))throw new Exception("Method inventory changed");
        if(!a.MainModule.AssemblyReferences.Select(r=>r.FullName).SequenceEqual(b.MainModule.AssemblyReferences.Select(r=>r.FullName)))throw new Exception("Assembly references changed");
        int changed=0;
        foreach(var key in before.Keys) {
            var old=before[key];var current=after[key];
            if(Body(old).SequenceEqual(Body(current))) continue;
            if(old.DeclaringType.FullName!="inXile.UI.TTON.MessageWindow"||old.Name!="SetMessage")throw new Exception("Unexpected method change: "+key);
            var suffix=current.Body.Instructions.Skip(17).ToArray();
            if(suffix.Length!=old.Body.Instructions.Count)throw new Exception("Original body length changed");
            for(int j=0;j<suffix.Length;j++) {
                if(suffix[j].OpCode!=old.Body.Instructions[j].OpCode)throw new Exception("Original opcode changed");
                // Original methods contain no branches into the injected prefix.
                var left=old.Body.Instructions[j].Operand;var right=suffix[j].Operand;
                if(left is Instruction) {
                    if(old.Body.Instructions.IndexOf((Instruction)left)!=Array.IndexOf(suffix,(Instruction)right))throw new Exception("Original branch changed");
                } else if((left==null?"":left.ToString())!=(right==null?"":right.ToString()))throw new Exception("Original operand changed");
            }
            changed++;Console.WriteLine("Expected changed method: "+key);
        }
        if(changed!=2)throw new Exception("Expected exactly two guarded entry changes");
        Console.WriteLine("Verified "+before.Count+" methods; exactly 2 guarded prefixes added; original method bodies and assembly references preserved");
    }
}
