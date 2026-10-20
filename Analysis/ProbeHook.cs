using System;
using System.Linq;
using Mono.Cecil;
using Mono.Cecil.Cil;
class ProbeHook {
    static void Main(string[] args) {
        var resolver = new DefaultAssemblyResolver();
        resolver.AddSearchDirectory(args[2]);
        var a=AssemblyDefinition.ReadAssembly(args[0],new ReaderParameters{AssemblyResolver=resolver});
        var h=AssemblyDefinition.ReadAssembly(args[1],new ReaderParameters{AssemblyResolver=resolver});
        var m=a.MainModule.Types.First(t=>t.FullName=="inXile.UI.TTON.MainMenuWindow").Methods.First(t=>t.Name=="Start");
        var method=h.MainModule.Types.First(t=>t.Name=="TutorialLayoutProbe").Methods.First(t=>t.Name=="Begin");
        var il=m.Body.GetILProcessor(); var first=m.Body.Instructions[0];
        il.InsertBefore(first,il.Create(OpCodes.Ldarg_0));
        il.InsertBefore(first,il.Create(OpCodes.Call,a.MainModule.ImportReference(method)));
        a.Write(args[3]);
    }
}
