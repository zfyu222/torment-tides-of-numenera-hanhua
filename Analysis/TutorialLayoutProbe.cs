using System;
using System.IO;
using System.Collections;
using System.Reflection;
using UnityEngine;
using UnityEngine.UI;
using inXile.UI;
using inXile.UI.TTON;

// Temporary QA hook only. Never part of the installed localization payload.
public class TutorialLayoutProbe : MonoBehaviour {
    public static void Begin(Component owner) { owner.gameObject.AddComponent<TutorialLayoutProbe>(); }
    IEnumerator Start() {
        yield return new WaitForSeconds(4);
        string folder = @"D:\StaticHanHua\Projects\torment-tides-of-numenera\Analysis";
        for (int i=0; i<4; i++) {
            TutorialMessageWindow window = inXile.UI.TTON.Windows.SpawnWindow<TutorialMessageWindow>();
            window.UnloadOnHide = true;
            window.SetMessage(i < 2 ? "原版译文排版" : "修复后排版", File.ReadAllText(Path.Combine(folder, "case"+i+".txt")), "继续", "");
            window.Show();
            yield return new WaitForSeconds(1);
            Text text = (Text)typeof(MessageWindow).GetField("messageLabel", BindingFlags.Instance|BindingFlags.NonPublic).GetValue(window);
            File.AppendAllText(Path.Combine(folder,"tutorial_probe.log"), i+" type="+text.GetType()+" font="+text.fontSize+" bestFit="+text.resizeTextForBestFit+" used="+text.cachedTextGenerator.fontSizeUsedForBestFit+" horizontal="+text.horizontalOverflow+" rect="+text.rectTransform.rect+" lines="+text.cachedTextGenerator.lineCount+" scale="+text.transform.lossyScale+"\n");
            while(window != null && window.gameObject.activeInHierarchy) yield return null;
        }
    }
}
