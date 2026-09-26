import struct, sys
def segs(d):
    out=[]; i=2
    while i+4<=len(d) and d[i]==0xFF:
        m=d[i+1]
        if m==0xD8: i+=2; continue
        if m==0xDA: break
        l=struct.unpack(">H",d[i+2:i+4])[0]; body=d[i+4:i+2+l]
        tag=body[:12].split(b"\0")[0][:28].decode("latin1","replace") if 0xE0<=m<=0xEF or m==0xFE else ""
        out.append((f"{m:02X}",tag,l)); i+=2+l
    # find primary EOI by scanning from SOS: approximate via last FFD9 before trailer? use first FFD9 after i with scan skip
    p=i
    while p+1<len(d):
        if d[p]==0xFF and d[p+1]==0xD9: break
        p+=1
    return out, len(d)-(p+2)
if __name__=="__main__":
    for f in sys.argv[1:]:
        s,t=segs(open(f,"rb").read()); print(f[-50:]); print("  ",s,"trailer",t)
