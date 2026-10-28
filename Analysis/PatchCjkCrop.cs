using System;
using System.Linq;
using System.Collections.Generic;
using Mono.Cecil;
using Mono.Cecil.Cil;

class PatchCjkCrop {
    static ModuleDefinition target;
    static Dictionary<MethodDefinition,MethodDefinition> methods=new Dictionary<MethodDefinition,MethodDefinition>();
    static TypeReference Type(TypeReference t) {
        if(t is ByReferenceType) return new ByReferenceType(Type(((ByReferenceType)t).ElementType));
        if(t is ArrayType) return new ArrayType(Type(((ArrayType)t).ElementType));
        var imported=target.ImportReference(t);
        if(imported.Scope is AssemblyNameReference) {
            var name=((AssemblyNameReference)imported.Scope).Name;
            imported.Scope=target.AssemblyReferences.First(r=>r.Name==name);
        }
        return imported;
    }
    static MethodReference Method(MethodReference m) {
        MethodDefinition definition=m as MethodDefinition;
        if(definition!=null && methods.ContainsKey(definition)) return methods[definition];
        var result=new MethodReference(m.Name,Type(m.ReturnType),Type(m.DeclaringType)) {
            HasThis=m.HasThis,ExplicitThis=m.ExplicitThis,CallingConvention=m.CallingConvention };
        foreach(var p in m.Parameters) result.Parameters.Add(new ParameterDefinition(Type(p.ParameterType)));
        return result;
    }
    static void Main(string[] args) {
        try { Build(args); }
        catch(Exception e) { Console.WriteLine(e.GetType().FullName+": "+e.Message); Environment.Exit(1); }
    }
    static void Build(string[] args) {
        var resolver=new DefaultAssemblyResolver(); resolver.AddSearchDirectory(args[3]);
        var original=AssemblyDefinition.ReadAssembly(args[0],new ReaderParameters { AssemblyResolver=resolver }); target=original.MainModule;
        string[] refs=target.AssemblyReferences.Select(r=>r.FullName).ToArray();
        var helper=AssemblyDefinition.ReadAssembly(args[1]).MainModule.Types.Single(t=>t.Name=="CjkRichTextCrop");
        if(target.Types.Any(t=>t.Name==helper.Name)) throw new Exception("Patch already installed");
        var clone=new TypeDefinition("InXile.Strings",helper.Name,helper.Attributes,Type(helper.BaseType));
        target.Types.Add(clone);
        foreach(var m in helper.Methods) {
            var n=new MethodDefinition(m.Name,m.Attributes,Type(m.ReturnType)); clone.Methods.Add(n); methods[m]=n;
            foreach(var p in m.Parameters) n.Parameters.Add(new ParameterDefinition(p.Name,p.Attributes,Type(p.ParameterType)));
        }
        foreach(var pair in methods) {
            var old=pair.Key; var next=pair.Value;
            next.Body.InitLocals=old.Body.InitLocals; next.Body.MaxStackSize=old.Body.MaxStackSize;
            foreach(var v in old.Body.Variables) next.Body.Variables.Add(new VariableDefinition(Type(v.VariableType)));
            var map=new Dictionary<Instruction,Instruction>();
            foreach(var i in old.Body.Instructions) { var n=Instruction.Create(OpCodes.Nop); n.OpCode=i.OpCode; next.Body.Instructions.Add(n); map[i]=n; }
            foreach(var i in old.Body.Instructions) {
                object o=i.Operand;
                if(o is Instruction) o=map[(Instruction)o];
                else if(o is Instruction[]) o=((Instruction[])o).Select(v=>map[v]).ToArray();
                else if(o is VariableDefinition) o=next.Body.Variables[old.Body.Variables.IndexOf((VariableDefinition)o)];
                else if(o is ParameterDefinition) o=next.Parameters[old.Parameters.IndexOf((ParameterDefinition)o)];
                else if(o is MethodReference) o=Method((MethodReference)o);
                else if(o is TypeReference) o=Type((TypeReference)o);
                else if(o is FieldReference) throw new Exception("Unexpected helper field dependency");
                map[i].Operand=o;
            }
            if(old.Body.ExceptionHandlers.Count!=0) throw new Exception("Unexpected helper exception block");
        }
        var crop=target.Types.Single(t=>t.FullName=="InXile.Strings.StringCropper").Methods.Single(m=>m.Name=="CropString");
        var gui=target.Types.Single(t=>t.FullName=="GUIUtils").Methods.Single(m=>m.Name=="GetText_TTON" && m.Parameters.Count==1);
        var il=crop.Body.GetILProcessor(); var first=crop.Body.Instructions[0];
        var prefix=new [] { il.Create(OpCodes.Ldarg_1), il.Create(OpCodes.Call,clone.Methods.Single(m=>m.Name=="HasCjk")),
            il.Create(OpCodes.Brfalse,first),il.Create(OpCodes.Ldarg_1),il.Create(OpCodes.Ldc_I4,70),
            il.Create(OpCodes.Ldc_I4,1228),il.Create(OpCodes.Call,gui),
            il.Create(OpCodes.Call,clone.Methods.Single(m=>m.Name=="Crop")),il.Create(OpCodes.Ret) };
        foreach(var i in prefix) il.InsertBefore(first,i);
        crop.Body.MaxStackSize=Math.Max(crop.Body.MaxStackSize,3);
        // ImportReference can add the compiler's mscorlib version. All references
        // are rebound above to the game's existing identity, so remove unused additions.
        foreach(var r in target.AssemblyReferences.ToArray()) if(!refs.Contains(r.FullName)) target.AssemblyReferences.Remove(r);
        original.Write(args[2]);
        Console.WriteLine("CJK rich-text crop injected; existing English body and tutorial patch retained.");
    }
}
