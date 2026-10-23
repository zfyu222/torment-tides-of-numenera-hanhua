using System;
using System.Linq;
using Mono.Cecil;
using Mono.Cecil.Cil;
class BestFitProbeHook {
    static void Main(string[] args) {
        var resolver=new DefaultAssemblyResolver();resolver.AddSearchDirectory(args[2]);
        var a=AssemblyDefinition.ReadAssembly(args[0],new ReaderParameters{AssemblyResolver=resolver});
        var probe=AssemblyDefinition.ReadAssembly(args[1],new ReaderParameters{AssemblyResolver=resolver});
        var begin=probe.MainModule.Types.Single(t=>t.Name=="TutorialBestFitProbe").Methods.Single(m=>m.Name=="Begin");
        var awake=a.MainModule.Types.Single(t=>t.Name=="GameState").Methods.Single(m=>m.Name=="Awake");
        awake.Body.GetILProcessor().InsertBefore(awake.Body.Instructions[0],Instruction.Create(OpCodes.Call,a.MainModule.ImportReference(begin)));
        a.Write(args[3]);
    }
}
