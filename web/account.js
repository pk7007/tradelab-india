const AccountMath = {
  positions(data) {
    const net=Array.isArray(data?.net)?data.net:[];
    return {open:net.filter(x=>Number(x.quantity)!==0), pnl:net.reduce((n,x)=>n+Number(x.pnl||0),0)};
  }
};
if(typeof module!=='undefined')module.exports=AccountMath;
