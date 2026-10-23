using System;
using System.Linq;
using Mono.Cecil;
using Mono.Cecil.Cil;

// Build a standalone assembly patch. No runtime DLL or plugin dependencies added.
class TutorialBestFitPatch {
    static void Main(string[] args) {
        var resolver = new DefaultAssemblyResolver();
        resolver.AddSearchDirectory(args[2]);
        var a = AssemblyDefinition.ReadAssembly(args[0], new ReaderParameters { AssemblyResolver = resolver });
        var module = a.MainModule;
        var message = module.Types.Single(t => t.FullName == "inXile.UI.TTON.MessageWindow");
        var tutorial = module.Types.Single(t => t.FullName == "inXile.UI.TTON.TutorialMessageWindow");
        var field = message.Fields.Single(f => f.Name == "messageLabel");
        var ui = AssemblyDefinition.ReadAssembly(System.IO.Path.Combine(args[2], "UnityEngine.UI.dll"));
        var text = ui.MainModule.Types.Single(t => t.FullName == "UnityEngine.UI.Text");
        var setFit = module.ImportReference(text.Methods.Single(m => m.Name == "set_resizeTextForBestFit"));
        var setOverflow = module.ImportReference(text.Methods.Single(m => m.Name == "set_verticalOverflow"));
        // Bind to the game's existing System reference, not the patch builder's CLR.
        var regex = new TypeReference("System.Text.RegularExpressions", "Regex", module,
            module.AssemblyReferences.Single(r => r.Name == "System"));
        var isMatch = new MethodReference("IsMatch", module.TypeSystem.Boolean, regex) { HasThis = false };
        isMatch.Parameters.Add(new ParameterDefinition(module.TypeSystem.String));
        isMatch.Parameters.Add(new ParameterDefinition(module.TypeSystem.String));
        foreach (var method in message.Methods.Where(m => m.Name == "SetMessage")) {
            var msg = method.Parameters[method.Parameters.Count == 1 ? 0 : 1];
            var il = method.Body.GetILProcessor();
            var first = method.Body.Instructions[0];
            var instructions = new [] {
                il.Create(OpCodes.Ldarg_0), il.Create(OpCodes.Isinst, tutorial), il.Create(OpCodes.Brfalse, first),
                il.Create(OpCodes.Ldarg, msg), il.Create(OpCodes.Brfalse, first),
                il.Create(OpCodes.Ldarg, msg), il.Create(OpCodes.Ldstr, "[\u3400-\u9fff]"),
                il.Create(OpCodes.Call, isMatch), il.Create(OpCodes.Brfalse, first),
                il.Create(OpCodes.Ldarg_0), il.Create(OpCodes.Ldfld, field), il.Create(OpCodes.Ldc_I4_0),
                il.Create(OpCodes.Callvirt, setFit),
                il.Create(OpCodes.Ldarg_0), il.Create(OpCodes.Ldfld, field), il.Create(OpCodes.Ldc_I4_1),
                il.Create(OpCodes.Callvirt, setOverflow)
            };
            foreach (var i in instructions) il.InsertBefore(first, i);
            method.Body.MaxStackSize = Math.Max(method.Body.MaxStackSize, 2);
        }
        a.Write(args[1]);
        Console.WriteLine("Patched only the two MessageWindow.SetMessage overloads; guarded by tutorial type and CJK text");
    }
}
