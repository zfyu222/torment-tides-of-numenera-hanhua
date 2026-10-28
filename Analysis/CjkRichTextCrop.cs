using System;
using System.Text;

// Only the Chinese path calls this helper. The original English crop remains intact.
internal static class CjkRichTextCrop {
    internal static bool HasCjk(string value) {
        if(value == null) return false;
        for(int i=0;i<value.Length;i++) if(value[i]>='\u3400' && value[i]<='\u9fff') return true;
        return false;
    }
    // Unity's supported rich-text tags occupy no visible character positions.
    private static bool Tag(string s,int start,out int end,out string name,out bool closing,out bool quad) {
        end=-1; name=""; closing=false; quad=false;
        if(s[start]!='<') return false;
        end=s.IndexOf('>',start+1);
        if(end<0) return false;
        int a=start+1;
        if(a<end && s[a]=='/') { closing=true; a++; }
        int b=a;
        while(b<end && Char.IsLetter(s[b])) b++;
        name=s.Substring(a,b-a).ToLowerInvariant();
        if(b!=end && s[b]!='=' && !Char.IsWhiteSpace(s[b])) return false;
        quad=name=="quad";
        return name=="b" || name=="i" || name=="color" || name=="size" || name=="material" || name=="a" || quad;
    }
    internal static string Crop(string s,int limit,string indicator) {
        if(s==null || limit<1) return s;
        var output=new StringBuilder();
        string[] stack=new string[s.Length]; int depth=0, visible=0, position=0;
        while(position<s.Length) {
            int end; string name; bool closing, quad;
            if(Tag(s,position,out end,out name,out closing,out quad)) {
                if(quad && visible>=limit) break;
                output.Append(s,position,end-position+1);
                if(quad) visible++;
                else if(closing) {
                    // Valid input is properly nested. Never invent closure for unmatched source tags.
                    if(depth>0 && stack[depth-1]==name) depth--;
                } else stack[depth++]=name;
                position=end+1; continue;
            }
            if(visible>=limit) break;
            int width=Char.IsHighSurrogate(s[position]) && position+1<s.Length && Char.IsLowSurrogate(s[position+1]) ? 2:1;
            output.Append(s,position,width); position+=width; visible++;
        }
        if(position==s.Length) return s;
        while(depth>0) output.Append("</").Append(stack[--depth]).Append('>');
        output.Append(' ').Append(indicator);
        return output.ToString();
    }
}
